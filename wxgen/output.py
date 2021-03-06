import inspect
import netCDF4
import numpy as np
import sys
import wxgen.util
import datetime


def get_all():
   """ Returns a list of all output classes """
   temp = inspect.getmembers(sys.modules[__name__], inspect.isclass)
   return temp


def get(name):
   """ Returns an output object of a class with the given name """
   outputs = get_all()
   m = None
   for mm in outputs:
      if(name == mm[0].lower()):
         m = mm[1]
   if m is None:
      wxgen.util.error("Cannot find output called '%s'" % name)
   return m


class Output(object):
   """
   A class for outputing trajectory information to file
   """
   def __init__(self, filename):
      self.filename = filename
      self.which_vars = None
      self.lat = None
      self.lon = None
      self.write_indices = False

   def write(self, trajectories, database, scale):
      """ Writes trajectories to file

      Arguments:
         trajectories (list): List of wxgen.trajectory
         database (wxgen.database): Database belonging to trajectories
         scale (str): One of "agg", "large", or "small"
      """
      raise NotImplementedError()


class Text(Output):
   """
   Writes the trajectories to a text file. One variable in each column and each day on a separate
   line. Trajectories are separated by a blank line.
   """
   def write(self, trajectories, database, scale):
      fid = open(self.filename, "w")
      N = len(trajectories)
      T = trajectories[0].length
      V = len(trajectories[0].variables)
      for n in range(0, N):
         values = database.extract(trajectories[n])
         for t in range(0, T):
            for v in range(0, V):
               fid.write("%f " % values[t, v])
            fid.write("\n")
         if n < N-1:
            fid.write("\n")
      fid.close()


class Netcdf(Output):
   """
   Writes the trajectories to a netcdf file.
   """
   def write(self, trajectories, database, scale, start_date=20170101):
      if len(trajectories) == 0:
         wxgen.util.error("No trajectories to write")
      file = netCDF4.Dataset(self.filename, 'w')

      file.createDimension("time")
      file.createDimension("ensemble_member", len(trajectories))
      use_single_gridpoint = self.lat is not None and self.lon is not None
      if scale != "agg":
         if scale == "large":
            xname = "longitude"
            yname = "latitude"
         elif scale == "small":
            xname = "x"
            yname = "y"
         else:
            wxgen.util.error("Cannot understand scale '%s'" % scale)

         if use_single_gridpoint:
            file.createDimension(yname, 1)
            file.createDimension(xname, 1)
         else:
            file.createDimension(yname, database.Y)
            file.createDimension(xname, database.X)

      # Time
      var_time = file.createVariable("time", "i4", ("time"))
      start_unixtime = wxgen.util.date_to_unixtime(start_date)
      end_unixtime = start_unixtime + 86400 * trajectories[0].length
      var_time[:] = np.arange(start_unixtime, end_unixtime, 86400)
      var_time.units = "seconds since 1970-01-01 00:00:00 +00:00"
      var_time.standard_name = "time"
      var_time.long_name = "time"

      # Forecast reference time
      var_frt = file.createVariable("forecast_reference_time", "i4")
      var_frt[:] = start_unixtime
      var_frt.units = "seconds since 1970-01-01 00:00:00 +00:00"
      var_frt.standard_name = "forecast_reference_time"
      var_frt.long_name = "forecast_reference_time"

      # Projection
      var_proj = file.createVariable("projection_regular_ll", "i4")
      var_proj.grid_mapping_name = "latitude_longitude"
      var_proj.earth_radius = 6367470
      var_proj.proj4 = "+proj=longlat +a=6367470 +e=0 +no_defs"

      # Latitude
      if scale == "large":
         var_lat = file.createVariable("latitude", "f4", (yname, xname))
         var_lat.units = "degrees_north"
         var_lat.standard_name = "latitude"
         if use_single_gridpoint:
            var_lat[:] = self.lat
         else:
            var_lat[:] = database.lats

         # Longitude
         var_lon = file.createVariable("longitude", "f4", (yname, xname))
         var_lon.units = "degrees_east"
         var_lon.standard_name = "longitude"
         if use_single_gridpoint:
            var_lon[:] = self.lon
         else:
            var_lon[:] = database.lons
      elif scale == "small":
         var_lat = file.createVariable("latitude", "f4", (yname, xname))
         var_lat.units = "degrees_north"
         var_lat.standard_name = "latitude"
         var_lat[:] = database.lats

         # Longitude
         var_lon = file.createVariable("longitude", "f4", (yname, xname))
         var_lon.units = "degrees_east"
         var_lon.standard_name = "longitude"
         var_lon[:] = database.lons

      # Define forecast variables
      variables = database.variables
      vars = dict()
      for var in variables:
         if scale == "agg":
            vars[var.name] = file.createVariable(var.name, "f4", ("time", "ensemble_member"))
         else:
            vars[var.name] = file.createVariable(var.name, "f4", ("time", "ensemble_member", yname, xname))
         if var.units is not None:
            vars[var.name].units = var.units
         vars[var.name].grid_mapping = "projection_regular_ll"
         vars[var.name].coordinates = "latitude longitude"

      # Write forecast variables
      if use_single_gridpoint:
         Xref, Yref = wxgen.util.get_i_j(database.lats, database.lons, self.lat, self.lon)
      for v in range(0, len(variables)):
         for m in range(0, len(trajectories)):
            if scale == "agg":
               values = database.extract(trajectories[m])
               for v in range(0, len(variables)):
                  vars[variables[v].name][:, m] = values[:, v]
            else:
                  values = database.extract_grid(trajectories[m], variables[v])
                  # Insert a singleton dimension at dimension index 1
                  values = np.expand_dims(values, 1)
                  if use_single_gridpoint:
                     vars[variables[v].name][:, m, :, :] = values[:, :, Xref, Yref]
                  else:
                     vars[variables[v].name][:, m, :, :] = values[:, :, :, :]

      if self.write_indices:
         var_segment_member = file.createVariable("segment_member", "i4", ("time", "ensemble_member"))
         var_segment_leadtime = file.createVariable("segment_leadtime", "i4", ("time", "ensemble_member"))
         var_segment_leadtime.units = "day"
         var_segment_time = file.createVariable("segment_time", "i4", ("time", "ensemble_member"))
         var_segment_time.units = "seconds since 1970-01-01 00:00:00 +00:00"
         var_segment_time.standard_name = "time"
         var_segment_time.long_name = "time"
         for m in range(0, len(trajectories)):
            trajectory = trajectories[m]
            var_segment_member[:, m] = trajectory.indices[:, 0]
            var_segment_leadtime[:, m] = trajectory.indices[:, 1]
            var_segment_time[:, m] = database.inittimes[trajectory.indices[:, 0]]

      # Global attributes
      file.Conventions = "CF-1.0"
      file.history = "%s: Generated by wxgen" % datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S +00:00')
      file.close()
