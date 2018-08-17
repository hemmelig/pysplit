#!/usr/bin/env python3

"""
The Catalogue class - generate an instance of Catalogue and load existing catalogues
or create new ones from hyp files or the IRIS catalogue.

Methods
Load: loads a pre-existing catalogue, located at *path*
new_teleseismic_cat
new_local_cat
merge ???

Attributes
path: location of the catalogue

Author: Hemmelig
"""

# ----- Import dependencies -----
from abc import ABC, abstractmethod
import os
import sys
import glob
import pandas as pd
from obspy.clients.fdsn import Client
from obspy import UTCDateTime
from obspy.taup import TauPyModel
from obspy.geodetics import locations2degrees
from obspy.geodetics import gps2dist_azimuth
from obspy.core import read
from obspy.core import AttribDict
from math import sqrt
import numpy as np
from mpl_toolkits.basemap import Basemap

class Catalogue(ABC):
	"""
	Catalogue objects should be initiated with a path to the chosen directory.
	
	Methods
	Load catalogue (load a pre-existing catalogue)
	Teleseismic catalogue (create a new teleseismic catalogue - based on functionality from obspy)
	Local catalogue (create a new local catalogue - can be generated from hyp file)
	"""

	cmpaz  = {'N':0, 'Z':0, 'E':90}
	cmpinc = {'N':90, 'Z':0, 'E':90}

	def __init__(self, path, archive_path, receiver_path):
		"""
		An abstract base class for Catalogue. The classes LocalCatalogue and TeleseismicCatalogue 
		inherit from this class.

		Returns a Catalogue at *path*
		"""
		self.path = path
		self.archive = archive_path

		# Check if the path already exists - otherwise, create it.
		try:
			if not os.path.exists(path):
				os.makedirs(path)
				os.makedirs("{}/metafiles".format(path))
				os.makedirs("{}/data".format(path))
				os.makedirs("{}/tmp".format(path))
				os.makedirs("{}/plots".format(path))
				print("Catalogue located at {}.".format(path))
		except TypeError:
			print("TypeError: *path* should a string.")

		# Copy receiver file into metafiles directory
		os.system("cp {} {}/metafiles/receivers.txt".format(receiver_path, self.path))

		# Sources
		self.source_file = "{}/metafiles/sources.txt".format(self.path)
		self.source_cols = ['otime', 'evlat', 'evlon', 'evdep', 'evmag', 'sourceid']
		self.source_df   = pd.DataFrame(columns=self.source_cols)

		# Receivers
		self.receiver_file = "{}/metafiles/receivers.txt".format(self.path)
		self.receiver_cols = ['stat', 'lat', 'lon', 'dep', 'st_dep', 'et_dep', 'receiverid']
		self.receiver_df   = pd.read_csv(self.receiver_file, sep=',')

		# Arrivals
		self.arrival_file = "{}/metafiles/arrivals.txt".format(self.path)
		self.arrival_cols = ['sourceid', 'receiverid', 'traveltime', 'waveform?']
		self.arrival_df   = pd.DataFrame(columns=self.arrival_cols)

		super().__init__()


	@abstractmethod
	def generate_catalogue(self):
		pass

	@abstractmethod
	def get_arrivals(self):
		pass

	@abstractmethod
	def window_range(self):
		pass

	def get_waveforms(self):
		# Get window range
		window_range = self.window_range()

		for i, arrival in self.arrival_df.iterrows():
			# Based on the source and receiver ID's, retrieve the relevant information
			otime, evlat, evlon, evdep = self._get_source(self.source_df, arrival.sourceid)
			stat, slat, slon, sdep     = self._get_receiver(self.receiver_df, arrival.receiverid)

			# Calculate the azimuth between the source-receiver pair
			dist, az, baz = gps2dist_azimuth(evlat, evlon, slat, slon)

			print(otime, window_range, float(arrival.traveltime))
			print(type(window_range), type(arrival.traveltime))

			# Calculate reference time for window to download
			window_beg = otime + float(arrival.traveltime) - window_range
			window_end = otime + float(arrival.traveltime) + window_range

			# Reference times for SAC file
			o = otime - window_beg
			t0 = window_range

			# Download and trim each file from the archive
			for comp in ['Z', 'N', 'E']:
				evyear = str(window_beg.year)
				evjday = str(window_beg.julday)
				nxjday = str((window_beg + 86400).julday)

				# Julian day must be a 3 character string
				while (len(evjday) != 3):
					evjday = '0' + evjday
				while (len(nxjday) != 3):
					nxjday = '0' + nxjday

				# Copy all files for a given day + the next
				file_to_grab = '{}/{}/{}/*_{}_{}2.m'.format(self.archive, evyear, evjday, stat.upper(), comp)
				next_to_grab = '{}/{}/{}/*_{}_{}2.m'.format(self.archive, evyear, nxjday, stat.upper(), comp)

				# Grab files
				os.system('scp {} {}/tmp/.'.format(file_to_grab, self.path))
				if (window_beg.julday != window_end.julday):
					os.system('scp {} {}/tmp/.'.format(next_to_grab, self.path))

				files = sorted(glob.glob('{}/tmp/*_{}_{}2.m'.format(self.path, stat.upper(), comp)))
				print(files)

				try:
					file = files[0]
				except IndexError:
					print("File doesn't exist")
					continue

				st = read('{}/tmp/*_{}_{}2.m'.format(self.path, stat.upper(), comp))
				print(st)

				# Trim and save the file locally
				try:
					st.trim(window_beg, window_end)
					tr = st[0]
					print(tr)

					# Generate name of output file
					if not os.path.exists('{}/data/{}'.format(self.path, stat.upper())):
						os.makedirs('{}/data/{}'.format(self.path, stat.upper()))
					name = '{}/data/{}/event.{}.{}.{}'.format(self.path, stat.upper(), sourceid, stat.upper(), comp.lower())
					print(name)

					# Write the trimmed data to a SAC file
					tr.write(name, format="SAC")

					# Reload SAC file and update all the headers
					st = read(name)
					tr = st.traces[0]

					tr.stats.sac.stla   = slat
					tr.stats.sac.stlo   = slon
					tr.stats.sac.stel   = sdep
					tr.stats.sac.cmpaz  = str(cmpaz[comp])
					tr.stats.sac.cmpinc = str(cmpinc[comp])
					tr.stats.sac.kcmpnm = 'HH' + comp
					tr.stats.t0         = t0
					tr.stats.kt5        = 3
					tr.stats.kt0        = 3
					tr.stats.sac.o      = o
					tr.stats.sac.evla   = evlat
					tr.stats.sac.evlo   = evlon
					tr.stats.sac.evdp   = evdep
					tr.stats.sac.dist   = dist / 1000.
					tr.stats.sac.az     = az

					tr.write(name, format="SAC")
					del name

					for l in files:
						os.remove(l)
					del files
				except:
					print("Error here")
					for l in files:
						os.remove(l)
					del files
					continue

	def load_sources(self):
		# Load sources
		try:
			self.source_df = pd.read_csv(self.source_file, sep=',')
			self.source_df['otime'] = self.source_df['otime'].apply(UTCDateTime)
			return True
		except:
			return False

	def load_receivers(self):
		# Load receivers
		try:
			self.receiver_df = pd.read_csv(self.receiver_file, sep=',')
			self.receiver_df['st_dep'] = self.receiver_df['st_dep'].apply(UTCDateTime)
			self.receiver_df['et_dep'] = self.receiver_df['et_dep'].apply(UTCDateTime)
			return True		
		except:
			return False

	def load_arrivals(self):
		# Load arrivals
		try:
			self.arrival_df = pd.read_csv(self.arrival_file, sep=',')
			return True
		except:
			return False

	def filter_spatially(self):
		pass

	def filter_temporally(self):
		pass

	def _get_receiver(self, df, id):
		stat = df.query('receiverid == @id')['stat'].iloc[0]
		slat = df.query('receiverid == @id')['lat'].iloc[0]
		slon = df.query('receiverid == @id')['lon'].iloc[0]
		sdep = df.query('receiverid == @id')['dep'].iloc[0]
		return stat, slat, slon, sdep

	def _get_source(self, df, id):
		otime = df.query('sourceid == @id')['otime'].iloc[0]
		evlat = df.query('sourceid == @id')['evlat'].iloc[0]
		evlon = df.query('sourceid == @id')['evlon'].iloc[0]
		evdep = df.query('sourceid == @id')['evdep'].iloc[0]
		return UTCDateTime(otime), evlat, evlon, evdep

	@abstractmethod
	def plot_geographic(self):
		pass

class LocalCatalogue(Catalogue):
	"""

	"""

	def generate_catalogue(self, hyp_file):
		"""
		Extracts earthquake information from a hyp file and
		creates a catalogue.
		"""

		if not os.path.exists(hyp_file):
			print("File doesn't exist.")
			print("Please provide a valid path.")

		# Copy the hyp file across into the catalogue directory
		head, tail = os.path.split(hyp_file)
		os.system("cp {} {}/metafiles/{}".format(hyp_file, self.path, tail))

		self.source_df = self._read_events_from_hyp(hyp_file)

		# Output the catalogue
		self.source_df.to_csv(self.source_file, index=False)

	def get_arrivals(self, hyp_file):
		"""
		Extracts S-phase arrival times from a hyp file and creates a 
		list of arrivals.
		"""
		lines = []
		S_lines = []
		with open(hyp_file, 'r') as f:
			for line in f:
				if ">" in line:
					if " P " in line:
						continue
					else:
						lines.append(line)

				if (">" in line) and (" S " in line):
					S_lines.append(line)

		# Preallocate space for the arrivals DataFrame
		self.arrival_df = pd.DataFrame(index=np.arange(0, len(S_lines)), columns=self.arrival_cols)

		sourceid = -1
		# Every time a line starting with PHASE is passed, increment the sourceid
		for i in range(len(lines)):
			line = lines[i].rstrip().split()

			if line[0] == "PHASE":
				sourceid += 1
				continue

			else:
				idx = i - (sourceid + 1)
				print(line[0])
				station = line[0]
				try:
					self.arrival_df.loc[idx] = [sourceid, self._lookup_receiver_id(station), line[15], False]
				except:
					print(station, " not found, check it exists?")
					self.arrival_df.loc[idx] = ["-", "-", "-", "-"]
					continue

		# Remove all events that didn't have complete information
		self.arrival_df = self.arrival_df.drop(self.arrival_df[self.arrival_df.sourceid == "-"].index)

		# Reset the index
		self.arrival_df.index = pd.RangeIndex(len(self.arrival_df.index))

		# Output the catalogue
		self.arrival_df.to_csv(self.arrival_file, index=False)

	def _read_events_from_hyp(self, hyp_file):
		"""
		Read in the contents of the hyp file.
		"""
		lines = []
		with open(hyp_file, 'r') as f:
			for line in f:
				if "GEOGRAPHIC" in line:
					lines.append(line)

		# Create DataFrame for event information. Space preallocated to
		# improve efficiency.
		source_df = pd.DataFrame(index=np.arange(0, len(lines)), columns=self.source_cols)

		for i in range(len(lines)):
			line = lines[i].rstrip().split()

			# Get origin time
			evyear, evmonth, evday  = int(line[2]), int(line[3]), int(line[4])
			evhour, evmin, evsecflt = int(line[5]), int(line[6]), float(line[7])
			evsec  = int(evsecflt)
			evmsec = int(1e6 * (evsecflt - evsec))
			otime  = UTCDateTime(evyear, evmonth, evday, evhour, evmin, evsec, evmsec)

			# Get hypocentral location
			evlat = float(line[9])
			evlon = float(line[11])
			evdep = float(line[13])
			evmag = "?"

			source_df.loc[i] = [otime, evlat, evlon, evdep, evmag, i]

		return source_df

	def _lookup_receiver_id(self, station):
		"""
		Takes a station name and looks up the receiver ID
		"""
		return self.receiver_df.query('stat == @station')["receiverid"].iloc[0]

	def window_range(self):
		return 60.

	def plot_geographic(self, ax, resolution='c'):

		# Find appropriate geographical region
		lons = self.source_df.evlon.values
		lats = self.source_df.evlat.values

		londiff = (lons.max() - lons.min()) * 0.1
		latdiff = (lats.max() - lats.min()) * 0.1
		lon0 = lons.min() - londiff
		lon1 = lons.max() + londiff
		lat0 = lats.min() - latdiff
		lat1 = lats.max() + latdiff

		# Create a Basemap of the calculated region and draw any coastlines
		self.m = Basemap(llcrnrlon=lon0, llcrnrlat=lat0, urcrnrlon=lon1, urcrnrlat=lat1,\
            resolution=resolution, projection='merc', ax=ax)
		self.m.drawcoastlines()

		# Set plot details (axes labels etc)
		ax.set_xlabel("Longitude, degrees", fontsize=10)
		ax.set_ylabel("Latitude, degrees", fontsize=10)

		x, y = self.m(lons, lats)
		tolerance = 10
		for i in range(len(x)):
			self.m.scatter(x[i], y[i], 12, marker='o', color='k', picker=tolerance, zorder=10, label="EVENT: {}".format(self.source_df.sourceid[i]))

	def plot_stations(self, ax):
		lons = self.receiver_df.lon.values
		lats = self.receiver_df.lat.values
		x, y = self.m(lons, lats)
		tolerance = 10
		for i in range(len(x)):
			self.m.scatter(x[i], y[i], 75, marker="v", color="green", picker=tolerance, zorder=15, label="STAT: {}".format(self.receiver_df.stat[i]))

class TeleseismicCatalogue(Catalogue):
	"""

	"""

	def generate_catalogue(self, starttime="1990-01-01", endtime="2018-01-01", minmag=0, lon=0.0, lat=0.0, minrad=0, maxrad=180):
		# Initialise a client object
		client = Client("IRIS")

		# Convert provided start and end times to UTCDateTime
		st = UTCDateTime(starttime)
		et = UTCDateTime(endtime)

		sources = client.get_events(starttime=st, endtime=et, minmagnitude=minmag,
								latitude=lat, longitude=lon, minradius=minrad,
								maxradius=maxrad)

		# Create DataFrame for event information. Space preallocated to
		# improve efficiency.
		self.source_df = pd.DataFrame(index=np.arange(0, sources.count()), columns=self.source_cols)

		for i in range(sources.count()):
			try:
				event = sources[i]
				otime = event.preferred_origin().get('time')
				evlat = event.preferred_origin().get('latitude')
				evlon = event.preferred_origin().get('longitude')
				evdep = event.preferred_origin().get('depth') / 1000.0
				evmag = event.preferred_magnitude().get('mag')

				self.source_df.loc[i] = [otime, evlat, evlon, evdep, evmag, i]

			except:
				event = "-"
				otime = "-"
				evlat = "-"
				evlon = "-"
				evdep = "-"
				evmag = "-"

				self.source_df.loc[i] = [otime, evlat, evlon, evdep, evmag, i]

		# Remove all events that didn't have complete information
		self.source_df = self.source_df.drop(self.source_df[self.source_df.otime == "-"].index)

		# Reset the index
		self.source_df.index = pd.RangeIndex(len(self.source_df.index))

		# Output the catalogue
		self.source_df.to_csv(self.source_file, index=False)

	def get_arrivals(self, phases=["SKS"]):
		# Initialise the velocity model
		model = TauPyModel(model="ak135")

		# Evaluate the arrivals
		for i, receiver in self.receiver_df.iterrows():
			print("i", i)
			# Filter for events occurring during station deployment
			tmp_df = self.source_df[self.source_df['otime'].between(receiver.st_dep, receiver.et_dep)]

			for j, source in tmp_df.iterrows():
				print("j", j)
				tmp_dist = locations2degrees(source.evlat, source.evlon, receiver.lat, receiver.lon)
				phase_arr = model.get_travel_times(source_depth_in_km=source.evdep,
												   distance_in_degree=tmp_dist,
												   phase_list=phases,
												   receiver_depth_in_km=receiver.dep)
				if not phase_arr:
					continue
				else:
					tmp = pd.DataFrame([int(source.sourceid), int(receiver.receiverid), phase_arr[0].time], index=self.arrival_cols).T
					self.arrival_df = self.arrival_df.append(tmp, ignore_index=True)

		self.arrival_df.to_csv(self.arrival_file, index=False)

	def window_range(self):
		return 300.

	def plot_geographic(self, ax):
		# Find the centre of the array
		lon_cen = self.receiver_df.lon.mean()
		lat_cen = self.receiver_df.lat.mean()

		# Retrieve the event longitudes and latitudes
		lons = self.source_df.evlon.values
		lats = self.source_df.evlat.values

		# Create a Basemap of the calculated region and draw any coastlines
		self.m = Basemap(projection='aeqd', lon_0=lon_cen, lat_0=lat_cen, ax=ax)
		self.m.drawcoastlines()

		x, y = self.m(lons, lats)
		tolerance = 10
		for i in range(len(x)):
			self.m.scatter(x[i], y[i], 12, marker='o', color='k', picker=tolerance, zorder=10, label="EVENT: {}".format(self.source_df.sourceid[i]))

	def plot_stations(self, ax):
		pass
