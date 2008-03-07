# Import modules from standard Python library
import os, sys, re, datetime, shutil, StringIO

# Import additional third party modules
import matplotlib.numerix, numpy

# Import our custom modules
import common, xmlstore.util, xmlstore.xmlstore, plot

def getNetCDFFile(path):
    """Returns a NetCDFFile file object representing the NetCDF file
    at the specified path. The returned object follows
    Scientific.IO.NetCDFFile conventions.
    
    Note: this is the *only* function that needs to know which NetCDF
    module to use. All other functions just operate on an object
    returned by this function, and expect this object to follow
    Scientific.IO.NetCDFFile conventions. Thus adding/replacing a module
    for NetCDF support should only require a chnage in this function.
    """

    # First import NetCDF file format support (we do this here rather
    # than on import, because this module can be useful without NetCDF
    # support as well).
    
    # We prefer ScientificPython, but resort to pynetcdf if ScientificPython is not found.
    try:
        from Scientific.IO.NetCDF import NetCDFFile
    except Exception,e1:
        try:
            from pynetcdf import NetCDFFile
        except Exception,e2:
            print 'Cannot load Scientific.IO.NetCDF. Reason: %s.' % e1
            print 'Cannot load pynetcdf. Reason: %s.' % e2
            print 'Cannot load a module for NetCDF reading. Please install either ScientificPython or pynetcdf.'
            sys.exit(1)
        pyver = sys.version_info
        if (pyver[0]==2 and pyver[1]>=5) or pyver[0]>2:
            print 'Unable to load Scientific.IO.NetCDF. We will use pynetcdf for NetCDF support. Note though that pynetcdf has known incompatibilities with Python 2.5 and higher, and you are using Python %i.%i.%i.' % pyver[0:3]

    try:
        nc = NetCDFFile(path)
    except Exception, e:
        raise Exception('An error occured while opening the NetCDF file "%s": %s' % (path,str(e)))

    return nc

class LinkedFileVariableStore(plot.VariableStore,xmlstore.xmlstore.DataFileEx):

    class DataFileCache(xmlstore.xmlstore.TypedStore):
        def __init__(self,valueroot=None,adddefault = True):
            schemadom = os.path.join(common.getDataRoot(),'schemas/datafilecache/0001.xml')
            xmlstore.xmlstore.TypedStore.__init__(self,schemadom,valueroot,adddefault=adddefault)

        schemadict = None
        @staticmethod
        def getDefaultSchemas():
            if LinkedFileVariableStore.DataFileCache.schemadict==None:
                LinkedFileVariableStore.DataFileCache.schemadict = xmlstore.xmlstore.ShortcutDictionary.fromDirectory(os.path.join(common.getDataRoot(),'schemas/datafilecache'))
            return LinkedFileVariableStore.DataFileCache.schemadict

    class LinkedFileVariable(plot.Variable):

        def __init__(self,store,data,index):
            self.store = store
            self.data = data
            self.index = index

        def getName(self):
            return self.data[0]

        def getLongName(self):
            return self.data[1]

        def getUnit(self):
            return self.data[2]

        def getDimensions(self):
            return self.store.dimensionorder[:]

        def getSlice(self,bounds):
            assert False, 'This function must be implemented by inheriting class.'
            
    @classmethod
    def createTypedStore(ownclass):
        return LinkedFileVariableStore.DataFileCache()

    linkedfilename = 'linkedfile_metadata.xml'
    rootnodename = 'DataFile'

    @classmethod
    def createObject(ownclass,datafile,context,infonode,nodename):
        finfo = xmlstore.util.findDescendantNode(infonode,['fileinfo'])
        assert finfo!=None, 'Node "%s" lacks "fileinfo" attribute.' % node
        store = None
        type = finfo.getAttribute('type')
        if type=='pointsintime':
            store = LinkedMatrix(datafile,context,infonode,nodename,type=0,dimensions={'time':{'label':'time','datatype':'datetime','preferredaxis':'x'}},dimensionorder=('time',))
        elif type=='profilesintime':
            store = LinkedProfilesInTime(datafile,context,infonode,nodename,dimensions={'time':{'label':'time','datatype':'datetime','preferredaxis':'x'},'z':{'label':'depth','unit':'m','preferredaxis':'y'}},dimensionorder=('time','z'))
        elif type=='singleprofile' or type=='verticalgrid':
            store = LinkedMatrix(datafile,context,infonode,nodename,type=1)
        else:
            assert False, 'Linked file has unknown type "%s".' % node.type
        return store
        
    def __init__(self,datafile,context,infonode,nodename,dimensions={},dimensionorder=(),variables=[]):
    
        plot.VariableStore.__init__(self)
        xmlstore.xmlstore.DataFileEx.__init__(self,datafile,context,infonode,nodename)

        # Copy data from supplied dimensions and variables
        self.dimensions = {}
        for dimname,dimdata in dimensions.iteritems():
            self.dimensions[dimname] = plot.VariableStore.getDimensionInfo(self,None)
            self.dimensions[dimname].update(dimdata)
        self.vardata = list(variables)
        self.dimensionorder = list(dimensionorder)
        
        # Supplement dimensions and variables with information in
        # supplied XML node (if any)
        if infonode!=None:
            finfo = xmlstore.util.findDescendantNode(infonode,['fileinfo'])
            self.nodeid = infonode.getAttribute('name')

            # Get variables
            fvars = xmlstore.util.findDescendantNode(finfo,['filevariables'])
            if fvars!=None:
                for ch in fvars.childNodes:
                    if ch.nodeType==ch.ELEMENT_NODE and ch.localName=='filevariable':
                        longname = ch.getAttribute('label')
                        unit = ch.getAttribute('unit')
                        name = longname
                        self.vardata.append((name,longname,unit))

            # Get dimensions
            fdims = xmlstore.util.findDescendantNode(finfo,['filedimensions'])
            if fdims!=None:
                for ch in fdims.childNodes:
                    if ch.nodeType==ch.ELEMENT_NODE and ch.localName=='filedimension':
                        dimdata = plot.VariableStore.getDimensionInfo(self,None)
                        if ch.hasAttribute('label'):         dimdata['label']         = ch.getAttribute('label')
                        if ch.hasAttribute('unit'):          dimdata['unit']          = ch.getAttribute('unit')
                        if ch.hasAttribute('datatype'):      dimdata['datatype']      = ch.getAttribute('datatype')
                        if ch.hasAttribute('preferredaxis'): dimdata['preferredaxis'] = ch.getAttribute('preferredaxis')
                        id = ch.getAttribute('name')
                        if id=='': id = dimdata['label']
                        self.dimensions[id] = dimdata
                        self.dimensionorder.append(id)

        self.data = None
        
    def clear(self,clearfile=True):
        """Clears all data, and by default also clears the original datafile
        (if any). The metadata set on the object will be updated accordingly.
        """
        self.dataChanged(clearfile=clearfile)
        
    def setDataFile(self,datafile=None,cleardata=True):
        """Attaches a new data file as source of data. This will clear all
        metadata set on the object, and by default it will also clear any
        parsed data.
        """ 
        xmlstore.xmlstore.DataFileEx.setDataFile(self,datafile)
        if cleardata: self.data = None
        
    def setData(self,data,clearfile=True):
        """Sets a new data block, automatically updating the metadata set on
        the object. By default it will clear the original datafile (if any).
        """
        self.data = data
        self.dataChanged(clearfile=clearfile)
        
    def dataChanged(self,clearfile=True):
        """Event handler, to be called just after the data has changed.
        """
        if clearfile: self.setDataFile(None,cleardata=False)
        if self.data==None: return
        
        #print '%s - caching validation result and dimension boundaries.' % self.nodeid
        metadata = self.getMetaData()
        for dimname in self.getDimensionNames():
            dimnode = metadata['Dimensions'].getChildById('Dimension',id=dimname,create=True)
            assert dimnode!=None, 'Failed to create Dimension node for %s.' % dimname
            dimrange = self.calculateDimensionRange(dimname)
            if dimrange==None: continue
            minval,maxval = dimrange
            if self.getDimensionInfo(dimname)['datatype']=='datetime':
                dimnode['IsTimeDimension'].setValue(True)
                dimnode['MinimumTime'].setValue(common.num2date(minval))
                dimnode['MaximumTime'].setValue(common.num2date(maxval))
            else:
                dimnode['IsTimeDimension'].setValue(False)
                dimnode['Minimum'].setValue(minval)
                dimnode['Maximum'].setValue(maxval)
        metadata['Valid'].setValue(True)

    def getDimensionNames(self):
        """Returns the names of data dimensions.
        """
        return self.dimensionorder[:]
        
    def getDimensionInfo(self,dimname):
        """Returns information on the specified data dimension.
        see VariableStore.getDimensionInfo for the type of
        information returned.
        """
        return self.dimensions[dimname]
        
    def getDimensionRange(self,dimname):
        """Returns the range, i.e., the tuple (minimum, maximum) of the
        specified dimension.
        """
        if self.data==None and (self.datafile==None or not self.datafile.isValid()): return None
        
        metadata = self.getMetaData()
        dimnode = metadata['Dimensions'].getChildById('Dimension',dimname)
        if dimnode==None:
            try:
                self.getData()
            except Exception,e:
                pass
            dimnode = metadata['Dimensions'].getChildById('Dimension',dimname)
            assert dimnode!=None, 'Cannot locate node for dimension %s in data file cache.' % dimname
            
        if metadata['Valid'].getValue()==False: return None

        #print '%s - using cached bounds for %s.' % (self.nodeid,dimname)
        if dimnode['IsTimeDimension'].getValue():
            minval = dimnode['MinimumTime'].getValue()
            maxval = dimnode['MaximumTime'].getValue()
        else:
            minval = dimnode['Minimum'].getValue()
            maxval = dimnode['Maximum'].getValue()
        if minval==None and maxval==None: return None
        return (minval,maxval)
            
    def validate(self,callback=None):
        if self.data==None and (self.datafile==None or not self.datafile.isValid()): return False
        metadata = self.getMetaData()
        valid = metadata['Valid'].getValue()
        if valid==None:
            try:
                self.getData(callback=callback)
            except Exception,e:
                pass
            valid = metadata['Valid'].getValue()
            assert valid!=None, 'Information on validity of data file %s not in data file cache.' % self.nodeid
        #print '%s - using cached validation result.' % self.nodeid
        return valid
    
    def getVariableNames(self):
        """Returns the names of all variables in the store.
        """
        return [data[0] for data in self.vardata]

    def getVariableLongNames(self):
        """Returns the long name of the specified variable.
        """
        return dict([(data[0],data[1]) for data in self.vardata])

    def getVariable(self,varname):
        """Returns the specified variable as LinkedFileVariable object.
        """
        for (index,data) in enumerate(self.vardata):
            if data[0]==varname:
                return self.variableclass(self,data,index)
        assert False, 'Variable with name "%s" not found in store.' % varname
        
    def saveToFile(self,path,callback=None):
        """Saves the current data to file."""
        if self.datafile!=None:
            self.datafile.saveToFile(path)
        else:
            f = open(path,'w')
            self.writeData(f,callback=callback)
            f.close()
            
    def getDataFile(self,callback=None):
        if self.datafile==None:
            assert self.data!=None, 'getDataFile called with both the data file and the data in memory are not set.'
        
            # Data not present as data file object. Create one in memory on the spot.
            target = StringIO.StringIO()
            self.writeData(target,callback=callback)
            self.datafile = xmlstore.xmlstore.DataFileMemory(target.getvalue(),self.nodeid+'.dat')
            target.close()
        return self.datafile.addref()
        
    def writeData(self,target,callback=None):
        """Writes the current data to a file-like object."""
        assert False, 'writeData must be implemented by derived class.'
        
    def getData(self,callback=None):
        if self.data==None and self.datafile!=None:
            try:
                data = self.parseDataFile(callback)
            except Exception,e:
                self.getMetaData()['Valid'].setValue(False)
                raise
            self.setData(data,clearfile=False)
        return self.data
        
    def parseDataFile(self,callback=None):
        assert False, 'parseDataFile must be implemented by derived class.'

class LinkedMatrix(LinkedFileVariableStore):

    class LinkedMatrixVariable(LinkedFileVariableStore.LinkedFileVariable):
        def getSlice(self,bounds):
            slice = self.Slice(self.getDimensions())
            
            # Get a reference to all data, and stop if the coordinate dimension is empty.
            data = self.store.getData()
            if data[0].shape[0]==0: return slice

            if slice.ndim==1:
                slice.coords[0] = data[0][:]
            slice.data = data[-1][:,self.index]
            slice.generateStaggered()
            return slice

    def __init__(self,datafile=None,context=None,infonode=None,nodename=None,type=0,dimensions={},dimensionorder=(),variables=[]):
        LinkedFileVariableStore.__init__(self,datafile,context,infonode,nodename,dimensions,dimensionorder,variables)
        self.variableclass = self.LinkedMatrixVariable
        assert len(self.dimensions)<=1, 'Linkedmatrix objects can only be used with 0 or 1 coordinate dimensions, but %i are present.' % len(self.dimensions)
        self.type = type
        
    def clear(self,clearfile=True):
        """Clears all contained data."""
        self.data = []
        if len(self.dimensions)==1:
            self.data.append(matplotlib.numerix.empty((0,)))
        self.data.append(matplotlib.numerix.empty((0,len(self.vardata))))
        LinkedFileVariableStore.clear(self,clearfile=clearfile)
        
    def calculateDimensionRange(self,dimname):
        ind = self.dimensionorder.index(dimname)
        dimdata = self.getData()[ind]
        if 0 in dimdata.shape: return None
        return (dimdata.min(),dimdata.max())

    def parseDataFile(self,callback=None):
        if self.datafile==None or not self.datafile.isValid(): return None

        if self.type==0:
            # Unknown number of rows
            res = self.loadDataFile_UnknownCount(callback)
        elif self.type==1:
            # Known number of rows
            res = self.loadDataFile_KnownCount(callback)
        else:
            assert False, 'unknown LinkedMatrix type %i.' % self.type

        return res
        
    def loadDataFile_KnownCount(self,callback):
        """Loads data from a DataFile object."""
        # Get number of dimensions and variables.
        dimcount = len(self.dimensions)
        varcount = len(self.vardata)

        # Get the size of the file (in bytes, may be None if the size is not known)
        # This will be used in combination with the position of the file pointer to report progress.
        filesize = float(self.datafile.getSize())
        
        # Access the data through some read-only file-like object.
        f = self.datafile.getAsReadOnlyFile()

        # First line contains number of observations to follow.
        line = f.readline()
        if line=='':
            raise Exception('File is empty. Expected number of observations on first line.')
        obscount = int(line)

        # Allocate arrays for storage of coordinates and variable values
        values = matplotlib.numerix.empty((obscount,varcount),matplotlib.numerix.Float32)
        if dimcount==1:
            # One coordinate dimension present; allocate an array for its values.
            dimtype = self.dimensions.values()[0]['datatype']
            dimisdate = (dimtype=='datetime')
            if dimisdate:
                datetimere = re.compile('(\d\d\d\d).(\d\d).(\d\d) (\d\d).(\d\d).(\d\d)')
                dimvalues = matplotlib.numerix.empty((obscount,),matplotlib.numerix.Float64)
                prevdate = None
            else:
                dimvalues = matplotlib.numerix.empty((obscount,),matplotlib.numerix.Float32)

        for irow in range(values.shape[0]):
            # Read a line (stop if end-of-file was reached)
            line = f.readline()
            if line=='':
                raise Exception('End-of-file reached after line %i, but expecting still %i more rows of observations.' % (irow+1,values.shape[0]-irow))
            iline = irow+2  # One-based line index
            
            if dimcount==1:
                if dimisdate:
                    # Read the date + time
                    datematch = datetimere.match(line)
                    if datematch==None:
                        raise Exception('Line %i does not start with time (yyyy-mm-dd hh:mm:ss). Line contents: %s' % (iline,line))
                    refvals = map(int,datematch.group(1,2,3,4,5,6)) # Convert matched strings into integers
                    dimvalue = xmlstore.util.dateTimeFromTuple(refvals)
                    if prevdate!=None and dimvalue<prevdate:
                        raise Exception('Line %i: observation time %s lies before previous observation time %s. Times should be increasing.' % (iline,dimvalue.strftime(xmlstore.util.datetime_displayformat),prevdate.strftime(common.datetime_displayformat)))
                    prevdate = dimvalue
                    dimvalue = common.date2num(dimvalue)
                
                    # Read variable values.
                    data = line[datematch.end()+1:].split()
                else:
                    # Split line, convert values to floats and store first as coordinate.
                    data = map(float,line.split())
                    dimvalue = data.pop(0)
            else:
                data = map(float,line.split())

            if len(data)<varcount:
                raise Exception('Line %i contains only %i observations, where %i are expected.' % (iline,len(data),varcount))
            
            # Store time and values.
            if dimcount==1: dimvalues[irow] = dimvalue
            values[irow,:] = data[:varcount]
            
            # Inform caller about progress
            if callback!=None and iline%1000==0:
                progress = None
                if filesize!=None:
                    try:
                        progress = float(f.tell())/filesize
                    except AttributeError:
                        progress = None
                callback(progress,'read %i lines.' % iline)
            
        # Close data file
        f.close()

        # Succeeded in reading the data: store them internally.
        if dimcount==1:
            return [dimvalues,values]
        else:
            return [values]

    def loadDataFile_UnknownCount(self,callback):
        varcount = len(self.vardata)
        
        # Get the size of the file (in bytes, may be None if the size is not known)
        # This will be used in combination with the position of the file pointer to report progress.
        filesize = float(self.datafile.getSize())
        
        # Access the data through some read-only file-like object.
        f = self.datafile.getAsReadOnlyFile()

        # Compile regular expression for reading dates.
        datetimere = re.compile('(\d\d\d\d).(\d\d).(\d\d) (\d\d).(\d\d).(\d\d)')
        
        # Size of one memory slab
        buffersize = 1000

        times = []
        values = []
        iline = 0
        while True:
            # Read a line (stop if end-of-file was reached)
            line = f.readline()
            if line=='': break

            # Calculate position in current memory slab, create new slab if needed.
            ipos = iline%buffersize
            if ipos==0:
                times.append(matplotlib.numerix.empty((buffersize,),matplotlib.numerix.Float64))
                values.append(matplotlib.numerix.empty((buffersize,varcount),matplotlib.numerix.Float32))

            # Increment current line number
            iline += 1
            
            # Read the date + time
            datematch = datetimere.match(line)
            if datematch==None:
                raise Exception('Line %i does not start with time (yyyy-mm-dd hh:mm:ss). Line contents: %s' % (iline,line))
            refvals = map(int,datematch.groups()) # Convert matched strings into integers
            curdate = xmlstore.util.dateTimeFromTuple(refvals)
            times[-1][ipos] = common.date2num(curdate)
            
            # Read values.
            data = line[datematch.end()+1:].split()
            if len(data)<varcount:
                raise Exception('Line %i contains only %i observations, where %i are expected.' % (iline,len(data),varcount))
            values[-1][ipos,:] = map(float,data[:varcount])
            
            # Inform caller about progress
            if callback!=None and iline%1000==0:
                progress = None
                if filesize!=None:
                    try:
                        progress = float(f.tell())/filesize
                    except AttributeError:
                        progress = None
                callback(progress,'read %i lines.' % iline)

        # Delete unused rows in last memory slab.
        times [-1] = times [-1][0:iline%buffersize]
        values[-1] = values[-1][0:iline%buffersize,:]
        
        # Concatenate memory slab.
        times = matplotlib.numerix.concatenate(times,axis=0)
        values = matplotlib.numerix.concatenate(values,axis=0)
            
        # Close data file
        f.close()

        # Succeeded in reading the data: store them internally.
        return [times,values]

    def writeData(self,target,callback=None):
        """Writes the current data to a file-like object."""
        # Get number of dimensions and variables, and get shortcuts to the data.
        dimcount = len(self.dimensions)
        data = self.getData()
        if dimcount==1:
            # One coordinate dimension present; get the data type of that dimension.
            dimdata = data[0]
            dimtype = self.dimensions.values()[0]['datatype']
            dimisdate = (dimtype=='datetime')
            if dimisdate: dimdata = common.num2date(dimdata)
        varcount = len(self.vardata)
        vardata = data[-1]
        
        if self.type==1:
            # Write first line with number of observations.
            target.write('%i\n' % vardata.shape[0])
        
        # Write lines with observations.
        for iline in range(vardata.shape[0]):
            if dimcount==1:
                if dimisdate:
                    target.write(dimdata[iline].strftime('%Y-%m-%d %H:%M:%S'))
                else:
                    target.write('%.9g' % dimdata[iline])
            for ivar in range(varcount):
                target.write('\t%.9g' % vardata[iline,ivar])
            target.write('\n')
            if callback!=None and iline%1000==0:
                callback(float(iline)/vardata.shape[0],'wrote %i lines.' % iline)

class LinkedProfilesInTime(LinkedFileVariableStore):

    class LinkedProfilesInTimeVariable(LinkedFileVariableStore.LinkedFileVariable):
        def getSlice(self,bounds):
            varslice = self.Slice(self.getDimensions())

            data = self.store.getGriddedData()
            if data[0].shape[0]==0: return varslice

            timebounds = common.findIndices(bounds[0],data[0])
            varslice.coords[0] = data[0][timebounds[0]:timebounds[1]+1]
            varslice.coords[1] = data[1]
            varslice.data = data[2][timebounds[0]:timebounds[1]+1,:,self.index]
            varslice.generateStaggered()
                    
            return varslice

    def __init__(self,datafile,context,infonode,nodename,dimensions=[],dimensionorder=(),variables=[]):
        LinkedFileVariableStore.__init__(self,datafile,context,infonode,nodename,dimensions,dimensionorder,variables)
        self.variableclass = self.LinkedProfilesInTimeVariable
        
    def setDataFile(self,datafile=None,cleardata=True):
        LinkedFileVariableStore.setDataFile(self,datafile,cleardata=cleardata)
        if cleardata: self.griddeddata = None

    def clear(self,clearfile=True):
        self.data = (matplotlib.numerix.empty((0,)),[],[])
        LinkedFileVariableStore.clear(self,clearfile=clearfile)

    def dataChanged(self,clearfile=True):
        """Event handler, must be called by external actors when they change the data."""
        self.griddeddata = None
        LinkedFileVariableStore.dataChanged(self,clearfile=clearfile)

    def calculateDimensionRange(self,dimname):
        ind = self.dimensionorder.index(dimname)
        dimdata = self.getData()[ind]
        if len(dimdata)==0: return None
        if ind==0:
            return (dimdata.min(),dimdata.max())
        else:
            dimmin,dimmax = dimdata[0].min(),dimdata[0].max()
            for iobs in range(1,len(dimdata)):
                dimmin = min(dimmin,dimdata[iobs].min())
                dimmax = max(dimmin,dimdata[iobs].max())
            return (dimmin,dimmax)
                
    def writeData(self,target,callback=None):
        """Writes the current data to a file-like object."""
        varcount = len(self.vardata)
        data = self.getData()
        assert data!=None, 'Cannot write data to file, because data is set to None.'
        times,depths,values = data
        for itime in range(times.shape[0]):
            target.write(common.num2date(times[itime]).strftime('%Y-%m-%d %H:%M:%S'))
            curdepths = depths[itime]
            curdata = values[itime]
            depthcount = len(curdepths)
            target.write('\t%i\t1\n' % depthcount)
            for idepth in range(depthcount):
                target.write('%.9g' % curdepths[idepth])
                for ivar in range(varcount):
                    target.write('\t%.9g' % curdata[idepth,ivar])
                target.write('\n')
        
    def getGriddedData(self,callback=None):
        data = self.getData()
        if self.griddeddata==None:
            times,depths,values = data
            
            varcount = len(self.vardata)
            
            # Find unique depth levels.
            uniquedepths = {}
            for ds in depths:
                for d in ds: uniquedepths[d] = True
            
            # Create depth grid to interpolate on to. Use the observation depths if less than 200,
            # otherwise create a equidistant 200-point grid between the minimum and maximum depth.
            uniquedepths = uniquedepths.keys()
            uniquedepths.sort()
            if len(uniquedepths)<200:
                depthgrid = matplotlib.numerix.array(uniquedepths,matplotlib.numerix.Float32)
            else:
                depthgrid = numpy.linspace(uniquedepths[0],uniquedepths[-1],200)
                
            # Grid observed profiles to depth grid.
            griddedvalues = matplotlib.numerix.empty((times.shape[0],depthgrid.shape[0],varcount),matplotlib.numerix.Float32)
            for it in range(len(times)):
                griddedvalues[it,:,:] = common.interp1(depths[it],values[it],depthgrid)
                if callback!=None and (it+1)%20==0:
                    callback(float(it+1)/len(times),'gridded %i profiles.' % (it+1))
                
            # Store time grid, depth grid and observations.
            self.griddeddata = (times,depthgrid,griddedvalues)
            
        return self.griddeddata

    def parseDataFile(self,callback=None):
        if self.datafile==None or not self.datafile.isValid(): return None
        
        varcount = len(self.vardata)
        
        # Get the size of the file (in bytes, may be None if the size is not known)
        # This will be used in combination with the position of the file pointer to report progress.
        filesize = float(self.datafile.getSize())
        
        # Access the data through some read-only file-like object.
        f = self.datafile.getAsReadOnlyFile()

        # Compile regular expression for reading dates.
        datetimere = re.compile('(\d\d\d\d).(\d\d).(\d\d) (\d\d).(\d\d).(\d\d)')

        times = []
        depths = []
        values = []
        iline = 0
        while True:
            # Read a line (stop if end-of-file was reached)
            line = f.readline()
            if line=='': break
            iline += 1
            
            # Read date & time
            datematch = datetimere.match(line)
            if datematch==None:
                raise Exception('Line %i does not start with time (yyyy-mm-dd hh:mm:ss). Line contents: %s' % (iline,line))
            refvals = map(int,datematch.group(1,2,3,4,5,6)) # Convert matched strings into integers
            curdate = xmlstore.util.dateTimeFromTuple(refvals)
            curdate = common.date2num(curdate)

            # Get the number of observations and the depth direction.
            (depthcount,updown) = map(int, line[datematch.end()+1:].split())

            # Create arrays that will contains depths and observed values.
            curdepths = matplotlib.numerix.empty((depthcount,),matplotlib.numerix.Float32)
            curvalues = matplotlib.numerix.empty((depthcount,varcount),matplotlib.numerix.Float32)
            
            # Depths can be increasing (updown==1) or decreasing (updown!=1)
            if updown==1:
                depthindices = range(0,depthcount,1)
            else:
                depthindices = range(depthcount-1,-1,-1)
            
            # Now parse the specified number of observations to create the profiles.
            prevdepth = None
            for idepthline in depthindices:
                if callback!=None and iline%1000==0:
                    pos = f.tell()
                    callback(pos/filesize,'processed %i lines.' % iline)
                    
                # Read line
                line = f.readline()
                if line=='':
                    raise Exception('Premature end-of-file after line %i; expected %i more observations.' % (iline,depthcount-depthindices.index(idepthline)))
                iline += 1
                
                # Read values (depth followed by data) and check.
                linedata = map(float,line.split())
                if len(linedata)<varcount+1:
                    raise Exception('Line %i contains only %i value(s), where %i (1 time and %i observations) are expected.' % (iline,len(linedata),varcount+1,varcount))
                if prevdepth!=None:
                    if linedata[0]==prevdepth:
                        raise Exception('Found duplicate observation for depth %.4f at line %i.' % (linedata[0],iline))
                    if updown==1:
                        if linedata[0]<prevdepth:
                            raise Exception('Observation depth decreases from %.4f to %.4f at line %i, but the profile depth was set to increase from first to last observation.' % (prevdepth,linedata[0],iline))
                    elif linedata[0]>prevdepth:
                        raise Exception('Observation depth increases from %.4f to %.4f at line %i, but the profile depth was set to decrease from first to last observation.' % (prevdepth,linedata[0],iline))
                prevdepth = linedata[0]
                
                # Store current observation
                curdepths[idepthline] = linedata[0]
                curvalues[idepthline,:] = linedata[1:varcount+1]
                
            # Append the profiles for the current time to the list.
            times.append(curdate)
            depths.append(curdepths)
            values.append(curvalues)
            
            # Inform caller about progress.
            if callback!=None and iline%1000==0:
                pos = f.tell()
                callback(pos/filesize,'processed %i lines.' % iline)
                
        # Convert sequence with times to numpy array.
        times = matplotlib.numerix.array(times,matplotlib.numerix.Float64)
        
        # Close data file
        f.close()

        # Succeeded in reading the data: store them internally.
        return [times,depths,values]

class NetCDFStore(plot.VariableStore,xmlstore.util.referencedobject):
    """Class encapsulating a NetCDF file.
    
    The file is expected to follow the COARDS convention.
    """
    
    class NetCDFVariable(plot.Variable):
        def __init__(self,store,varname):
            plot.Variable.__init__(self,store)
            self.varname = str(varname)

        def getName(self):
            return self.varname

        def getLongName(self):
            nc = self.store.getcdf()
            var = nc.variables[self.varname]
            if hasattr(var,'long_name'):
                return var.long_name
            else:
                return self.getName()

        def getUnit(self):
            nc = self.store.getcdf()
            cdfvar = nc.variables[self.varname]
            if not hasattr(cdfvar,'units'): return None
            return common.convertUnitToUnicode(cdfvar.units)
            
        def getDimensions(self):
          nc = self.store.getcdf()
          return nc.variables[self.varname].dimensions

        def getSlice(self,bounds):
          nc = self.store.getcdf()
            
          v = nc.variables[self.varname]
          dimnames = v.dimensions
          assert len(bounds)==len(dimnames), 'Number of specified bounds (%i) does not match number of dimensions (%i).' % (len(bounds),len(dimnames))
          
          varslice = self.Slice(dimnames)
          
          boundindices = []
          
          for idim,dimname in enumerate(dimnames):
            if dimname=='z' or dimname=='z1':
                # Get depth coordinates and bounds.
                (z,z1,z_stag,z1_stag) = self.store.getDepth()
                depthbounds = (0,z.shape[1])
                timebounds = boundindices[list(dimnames).index('time')]
                if dimname=='z':
                    varslice.coords     [idim] = z     [timebounds[0]:timebounds[1]+1,depthbounds[0]:depthbounds[1]+1]
                    varslice.coords_stag[idim] = z_stag[timebounds[0]:timebounds[1]+2,depthbounds[0]:depthbounds[1]+2]
                elif dimname=='z1':
                    varslice.coords     [idim] = z1     [timebounds[0]:timebounds[1]+1,depthbounds[0]+1:depthbounds[1]+2]
                    varslice.coords_stag[idim] = z1_stag[timebounds[0]:timebounds[1]+2,depthbounds[0]  :depthbounds[1]+2]
                boundindices.append(depthbounds)
            else:
                # Get coordinates and bounds of this dimension.
                (coords,coords_stag) = self.store.getCoordinates(dimname)
                if coords==None: return None
                curbounds = common.findIndices(bounds[idim],coords)
                varslice.coords     [idim] = coords     [curbounds[0]:curbounds[1]+1]
                varslice.coords_stag[idim] = coords_stag[curbounds[0]:curbounds[1]+2]
                boundindices.append(curbounds)

          slices = tuple([slice(b[0],b[1]+1) for b in boundindices])
          try:
            dat = matplotlib.numerix.asarray(v[slices])
          except Exception, e:
            raise Exception('Unable to read values for NetCDF variable "%s". Error: %s' % (self.varname,str(e)))

        # Process COARDS variable attributes.
          if hasattr(v,'missing_value'):
            dat = matplotlib.numerix.ma.masked_array(dat,dat==v.missing_value)
          if hasattr(v,'scale_factor'):
            dat *= v.scale_factor
          if hasattr(v,'add_offset'):
            dat += v.add_offset

          varslice.data = dat
        
          return varslice

    def __init__(self,path=None):
        xmlstore.util.referencedobject.__init__(self)
        plot.VariableStore.__init__(self)
        
        self.datafile = None
        self.nc = None

        self.cachedcoords = {}
        
        if path!=None: self.load(path)
        
    def __str__(self):
        return self.datafile
        
    def getDimensionInfo(self,dimname):
        res = plot.VariableStore.getDimensionInfo(self,dimname)
        varinfo = self.nc.variables[dimname]
        if hasattr(varinfo,'long_name'):
            res['label'] = varinfo.long_name
        else:
            res['label'] = dimname
        if hasattr(varinfo,'units'):     res['unit']  = varinfo.units
        if dimname=='z' or dimname=='z1':
            res['label'] = 'depth'
            res['preferredaxis'] = 'y'
            if res['unit']=='meters': res['unit']='m'
        elif self.isTimeDimension(dimname):
            res['datatype'] = 'datetime'
            res['preferredaxis'] = 'x'
            res['unit'] = ''
        return res
        
    def save(self,path):
        shutil.copyfile(self.datafile,path)

    def unlink(self):
        if self.nc!=None:
            # Close NetCDF result file.
            self.nc.close()
            self.nc = None
            
    def load(self,path):
        # Store link to result file, and try to open the CDF file
        self.datafile = path
        self.getcdf()

    def getcdf(self):
        """Returns a NetCDFFile file object representing the NetCDF file
        at the path in self.datafile. The returned object should follow
        Scientific.IO.NetCDFFile conventions.
        """
        if self.nc!=None: return self.nc
        assert self.datafile!=None, 'The result object has not yet been attached to an actual result.'
        self.nc = getNetCDFFile(self.datafile)
        return self.nc

    def getVariableNames(self):
        nc = self.getcdf()

        # Get names of NetCDF variables
        try:
          varNames = nc.variables.keys()
        except Exception, e:
            raise Exception('Unable to obtain NetCDF variable names, error: '+str(e))

        return varNames

    def getVariableLongNames(self):
      varnames = self.getVariableNames()
      nc = self.getcdf()
      vardict = {}
      for varname in varnames:
          vardict[varname] = nc.variables[varname].long_name
      return vardict

    def getVariable(self,varname,check=True):
        varname = str(varname)
        if check:
            nc = self.getcdf()
            vars = nc.variables
            if not (varname in vars): return None
        return self.NetCDFVariable(self,varname)
        
    def getCoordinates(self,dimname):
        if dimname not in self.cachedcoords:
            nc = self.getcdf()
            coords = matplotlib.numerix.asarray(nc.variables[dimname][:])
            
            if 0 in coords.shape:
                coords = None
                coords_stag = None
            else:
                assert len(coords.shape)==1, 'Currently only independent dimensions (coordinates of which do no vary along other dimensions) can be used.'
                
                istimedim = self.isTimeDimension(dimname)
                if istimedim:
                    timeunit,timeref = self.getTimeReference(dimname)
                    timeref = common.date2num(timeref)
                    coords = timeref+timeunit*matplotlib.numerix.asarray(coords,matplotlib.numerix.Float64)
                
                coords_stag = matplotlib.numerix.zeros((coords.shape[0]+1,),matplotlib.numerix.typecode(coords))
                if coords.shape[0]==1:
                    # Only one coordinate provided; use default step of one.
                    delta = 1.
                    if istimedim:
                        if self.scenario!=None:
                            delta = self.scenario['output/dtsave'].getValue(usedefault=True)
                            if delta!=None: delta = delta.getAsSeconds()/86400.
                        if delta==None:
                            if coords[0]>timeref:
                                delta=coords[0]-timeref
                            else:
                                delta=1.
                    coords_stag[0] = coords[0]-delta/2
                    coords_stag[1] = coords[0]+delta/2
                else:
                    coords_stag[1:-1] = coords[0:-1] + (coords[1:]-coords[0:-1])/2
                    coords_stag[0 ] = coords[0]  - (coords[ 1]-coords[ 0])/2
                    coords_stag[-1] = coords[-1] + (coords[-1]-coords[-2])/2

            self.cachedcoords[dimname]         = coords
            self.cachedcoords[dimname+'_stag'] = coords_stag

        return (self.cachedcoords[dimname],self.cachedcoords[dimname+'_stag'])

    def getDepth(self):
        if 'z' not in self.cachedcoords:
            nc = self.getcdf()

            # Get layer heights
            h = matplotlib.numerix.asarray(nc.variables['h'][:,:,0,0])
            
            # Get depths of interfaces
            z1 = h.cumsum(1)
            z1 = matplotlib.numerix.concatenate((matplotlib.numerix.zeros((z1.shape[0],1),matplotlib.numerix.typecode(z1)),z1),1)
            bottomdepth = z1[0,-1]-nc.variables['zeta'][0,0,0]
            z1 -= bottomdepth

            # Get depth of layer centers
            z = z1[:,1:z1.shape[1]]-0.5*h

            # Interpolate in depth to create staggered grid
            z1_med = matplotlib.numerix.concatenate((matplotlib.numerix.take(z1,(0,),0),z1,matplotlib.numerix.take(z1,(-1,),0)),0)
            z_stag = 0.5 * (z1_med[0:z1_med.shape[0]-1,:] + z1_med[1:z1_med.shape[0],:])
            
            z_med = matplotlib.numerix.concatenate((z,matplotlib.numerix.take(z1,(-1,),1)),1)
            z_med = matplotlib.numerix.concatenate((matplotlib.numerix.take(z_med,(0,),0),z_med,matplotlib.numerix.take(z_med,(-1,),0)),0)
            z1_stag = 0.5 * (z_med[0:z_med.shape[0]-1,:] + z_med[1:z_med.shape[0],:])
            
            z.shape = list(z.shape)+[1,1]
            z1.shape = list(z1.shape)+[1,1]
            z_stag.shape = list(z_stag.shape)+[1,1]
            z1_stag.shape = list(z1_stag.shape)+[1,1]

            self.cachedcoords['z']       = z
            self.cachedcoords['z1']      = z1
            self.cachedcoords['z_stag']  = z_stag
            self.cachedcoords['z1_stag'] = z1_stag

        return (self.cachedcoords['z'],self.cachedcoords['z1'],self.cachedcoords['z_stag'],self.cachedcoords['z1_stag'])
        
    class ReferenceTimeParseError(Exception):
        def __init__(self,error):
            Exception.__init__(self,error)
        
    def isTimeDimension(self,dimname):
        # See if specified dimension is a time dimension according to COARDS convention.
        try:
            timeunit,timeref = self.getTimeReference(dimname)
        except self.ReferenceTimeParseError:
            return False
        return True

    def getTimeReference(self,dimname):
      cdfvar = self.getcdf().variables[dimname]
      if not hasattr(cdfvar,'units'):
          raise self.ReferenceTimeParseError('variable "%s" lacks "units" attribute.' % (dimname,))
        
      # Retrieve time unit (in days) and reference date/time, based on COARDS convention.
      fullunit = cdfvar.units
      if ' since ' not in fullunit:
          raise self.ReferenceTimeParseError('"units" attribute of variable "%s" equals "%s", which does not follow COARDS convention. Problem: string does not contain " since ".' % (dimname,fullunit))
      timeunit,reftime = fullunit.split(' since ')
      
      # Parse the reference date, time and timezone
      datematch = re.match(r'(\d\d\d\d)[-\/](\d{1,2})-(\d{1,2})\s*',reftime)
      if datematch==None:
        raise self.ReferenceTimeParseError('"units" attribute of variable "time" equals "%s", which does not follow COARDS convention. Problem: cannot parse date in "%s".' % (fullunit,reftime))
      year,month,day = map(int,datematch.group(1,2,3))
      hour,min,sec = 0,0,0
      reftime = reftime[datematch.end():]
      if len(reftime)>0:
        timematch = re.match(r'(\d{1,2}):(\d{1,2}):(\d{1,2}(?:\.\d*)?)\s*',reftime)
        if timematch==None:
            raise self.ReferenceTimeParseError('"units" attribute of variable "time" equals "%s", which does not follow COARDS convention. Problem: cannot parse time in "%s".' % (fullunit,reftime))
        hour,min,sec = map(int,timematch.group(1,2,3))
        reftime = reftime[timematch.end():]
      dateref = datetime.datetime(year,month,day,hour,min,sec,tzinfo=xmlstore.util.utc)
      if len(reftime)>0:
        timezonematch = re.match(r'(-?\d{1,2})(?::?(\d\d))?$',reftime)
        if timezonematch==None:
            raise self.ReferenceTimeParseError('"units" attribute of variable "time" equals "%s", which does not follow COARDS convention. Problem: cannot parse time zone in "%s".' % (fullunit,reftime))
        if timezonematch.group(2)==None:
            dhour,dmin = int(timezonematch.group(1)),0
        else:
            dhour,dmin = map(int,timezonematch.group(1,2))
            if dhour<0: dmin = -dmin
        dateref -= datetime.timedelta(hours=dhour,minutes=dmin)
      
      # Get time unit in number of days.
      if timeunit in ('seconds','second','secs','sec','ss','s'):
          timeunit = 1./86400.
      elif timeunit in ('minutes','minute','mins','min'):
          timeunit = 1./1440.
      elif timeunit in ('hours','hour','hrs','hr','hs','h'):
          timeunit = 1./24.
      elif timeunit in ('days','day','ds','d'):
          timeunit = 1.
      elif timeunit in ('years','year','yrs','yr','ys','y'):
          timeunit = 365.   # udunits convention: year=365 days
      else:
          raise self.ReferenceTimeParseError('"units" attribute of variable "time" equals "%s", which does not follow COARDS convention. Problem: unknown time unit "%s".' % (fullunit,timeunit))
      
      return timeunit,dateref