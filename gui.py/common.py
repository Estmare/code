#!/usr/bin/python

#$Id: common.py,v 1.6 2007-01-11 15:56:28 jorn Exp $

import datetime,time
import xml.dom.minidom, os, re, sys
import zipfile, tarfile, tempfile, shutil

# Import NetCDF file format support
import pycdf

# Import all MatPlotLib libraries
import matplotlib
matplotlib.use('Qt4Agg')
matplotlib.rcParams['numerix'] = 'numeric'
import matplotlib.numerix,matplotlib.numerix.ma
import matplotlib.dates
import matplotlib.pylab

import scenarioformats

# Current GOTM/namelist version used by the gotm.so/gotm.pyd engine
gotmscenarioversion = 'gotm-3.3.2'
guiscenarioversion = 'gotmgui-0.5.0'
savedscenarioversion = 'gotm-3.3.2'

# datetime_displayformat: date format used to display datetime objects in the GUI.
datetime_displayformat = '%Y-%m-%d %H:%M:%S'
datetime_displayformat = '%x %X'

# dateformat: date format used for storing datetime objects in XML.
#   used in conversion of (XML) string to datetime, and vice versa.
dateformat = '%Y-%m-%d %H:%M:%S'

# parsedatetime: Convert string to Python datetime object, using specified format.
# Counterpart of datetime.strftime.
def parsedatetime(str,fmt):
    t1tmp = time.strptime(str,fmt) 
    return datetime.datetime(*t1tmp[0:6])

def getNamedArgument(name):
    try:
        iarg = sys.argv.index(name)
    except ValueError:
        return None
    val = sys.argv[iarg+1]
    del sys.argv[iarg+1]
    del sys.argv[iarg]
    return val

def findDescendantNode(root,location,create=False):
    if root==None: raise Exception('findDescendantNode called on non-existent parent node (parent = None).')
    node = root
    for childname in location:
        if childname=='': continue
        foundchild = None
        for ch in node.childNodes:
            if ch.nodeType==ch.ELEMENT_NODE and ch.localName==childname:
                foundchild = ch
                break
        if foundchild==None:
            if create:
                doc = root
                while doc.parentNode!=None: doc=doc.parentNode
                foundchild = doc.createElementNS(node.namespaceURI,childname)
                node.appendChild(foundchild)
            else:
                return None
        node = foundchild
    return node

def findDescendantNodes(root,location):
    parentloc = location[:]
    name = parentloc.pop()
    parent = findDescendantNode(root,parentloc,create=False)
    children = []
    if parent!=None:
        for ch in parent.childNodes:
            if ch.nodeType==ch.ELEMENT_NODE and ch.localName==name:
                children.append(ch)
    return children

def removeDescendantNodes(root,location):
    parentloc = location[:]
    name = parentloc.pop()
    parent = findDescendantNode(root,parentloc,create=False)
    if parent==None: return
    children = []
    for ch in node.childNodes:
        if ch.nodeType==ch.ELEMENT_NODE and ch.localName==name:
            children.append(ch)
    for ch in children:
        parent.removeChild(ch)
        ch.unlink()

def addDescendantNode(root,location):
    parentloc = location[:]
    name = parentloc.pop()
    parent = findDescendantNode(root,parentloc,create=True)
    if parent==None: raise Exception('Unable to locate or create parent node for "'+str(location)+'".')
    doc = root
    while doc.parentNode!=None: doc=doc.parentNode
    node = doc.createElementNS(parent.namespaceURI,name)
    parent.appendChild(node)
    return node

def readNamelist(string):
    restopchar = re.compile('[\'"/]')
    match = re.compile('\s*&\s*(\w+)\s*').match(string)
    if match==None:
        raise Exception('No namelist found; expected ampersand followed by namelist name.')
    name = match.group(1)
    istart = match.end(0)
    ipos = istart
    while True:
        match = restopchar.search(string,pos=ipos)
        if match==None:
            raise Exception('End of namelist (slash) not found.')
        ch = match.group(0)
        ipos = match.end(0)
        if ch=='/':
            break
        else:
            inextquote = string.find(ch,ipos)
            if inextquote==-1:
                raise Exception('Opening quote %s was not matched by end quote.' % ch)
            ipos = inextquote+1
    return (name,string[istart:ipos],string[ipos:])

# XMLPropertyStore: class for storing 'properties' (i.e name,value pairs) in
#   hierarchical structure, using in-memory XML DOM. All values are stored as
#   strings, since XML is text-based; strings are converted to and from other
#   types (date, int, float, bool) whenever necessary.
class XMLPropertyStore:
    
    # =========================================================================================
    # PROTECTED
    # =========================================================================================
    # __init__: constructor
    def __init__(self,xmldocument=None,xmlroot=None):
        if isinstance(xmldocument,str):
            if xmlroot!=None: raise 'Path to XML file specified, but also a (already parsed!) root node was supplied. This combination is invalid'
            xmldocument = xml.dom.minidom.parse(xmldocument)

        self.xmldocument = xmldocument
        if xmlroot==None: xmlroot = xmldocument.documentElement
        self.xmlroot = xmlroot
        self.xmlnamespace = self.xmldocument.namespaceURI

        self.filetypes = {'string'  :unicode,
                          'int'     :int,
                          'float'   :float,
                          'bool'    :bool,
                          'datetime':datetime.datetime}

    # =========================================================================================
    # PROTECTED
    # =========================================================================================
    # getText: gets all text directly below an XML element; may consist of multiple text nodes.
    def getText(self,node):
        rc = ''
        for ch in node.childNodes:
            if ch.nodeType == ch.TEXT_NODE: rc = rc + ch.data
        return rc

    # =========================================================================================
    # PROTECTED
    # =========================================================================================
    # getText: sets text directly below an XML element, using one text node
    #   replaces any existing child text nodes.
    def setText(self,node,text):
        for ch in node.childNodes:
            if ch.nodeType == ch.TEXT_NODE:
                node.removeChild(ch)
                ch.unlink()
        val = self.xmldocument.createTextNode(text)
        node.appendChild(val)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # setProperty: sets specified location (list of ancestor names) to specified value.
    #   autoconverts specified value to string format.
    def setProperty(self,location,value):
        node = findDescendantNode(self.xmlroot,location[:],create=True)
        if node==None: raise 'Unable to create new child node at '+str(location)
        return self.setNodeProperty(node,value)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # addProperty: adds a node at specified location (list of ancestor names) with specified
    #   value. Autoconverts specified value to string format.
    def addProperty(self,location,value):
        parentloc = location[:]
        name = parentloc.pop()
        parent = findDescendantNode(self.xmlroot,parentloc,create=True)
        if parent==None: raise Exception('Unable to locate or create parent node for "'+str(location)+'".')
        node = self.xmldocument.createElementNS(parent.namespaceURI,name)
        parent.appendChild(node)
        self.setNodeProperty(node,value)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # setNodeProperty: sets specified node to specified value.
    #   autoconverts specified value to string format.
    def setNodeProperty(self,node,value):
        value = self.packvalue(value)
        if self.getText(node)!=value:
            self.setText(node,value)
            return True
        else:
            return False

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # getProperty: gets value at specified location (list of ancestor names).
    #   autoconverts value to the type requested (otherwise value = string).
    def getProperty(self,location,valuetype=str):
        node = findDescendantNode(self.xmlroot,location[:])
        if node==None: return None
        return self.getNodeProperty(node,valuetype=valuetype)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # getNodeProperty: gets value at node.
    #   autoconverts value to the type requested (otherwise value = string).
    def getNodeProperty(self,node,valuetype=str):
        return self.unpackvalue(self.getText(node),valuetype=valuetype)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # clearProperty: removes all nodes with specified location (list of ancestor names).
    def clearProperty(self,location):
        parentloc = location[:]
        name = parentloc.pop()
        parent = findDescendantNode(self.xmlroot,parentloc,create=False)
        if parent==None: return
        children = []
        for ch in parent.childNodes:
            if ch.nodeType==ch.ELEMENT_NODE and ch.localName==name:
                children.append(ch)
        for ch in children:
            parent.removeChild(ch)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # clearNodeProperty: removes specified node.
    def clearNodeProperty(self,node):
        node.parentNode.removeChild(node)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # save: saves the current property tree to an XML document.
    def save(self,path):
        self.xmldocument.writexml(file(path,'w'),encoding='utf-8')

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # packvalue: converts a value to a string representation suitable for storing in XML.
    def packvalue(self,value):
        if isinstance(value,datetime.datetime):
            return value.strftime(dateformat)
        elif isinstance(value,bool):
            if value: return 'True'
            else:     return 'False'
        else:
            return unicode(value)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # unpackvalue: converts string representation of a value to the desired type.
    def unpackvalue(self,value,valuetype=str):
        if isinstance(valuetype,str) or isinstance(valuetype,unicode):
            if valuetype not in self.filetypes:
                raise Exception('unpackvalue: unknown type "' + valuetype + '" requested.')
            valuetype = self.filetypes[valuetype]
        if valuetype==datetime.datetime:
            return parsedatetime(value,dateformat)
        elif valuetype==bool:
            return (value=='True')
        else:
            return valuetype(value)

class DataFile:
    def __init__(self,path=None):
        if path!=None:
            self.path = unicode(path)
        else:
            self.path = None

    def __str__(self):
        if self.path==None: return ''
        return str(self.path)

    def __unicode__(self):
        if self.path==None: return ''
        return unicode(self.path)

    def getName(self):
        if self.path==None: return ''
        (path,name) = os.path.split(self.path)
        return name

    def isValid(self):
        return (self.path!=None and os.path.isfile(self.path))

    def getAsReadOnlyFile(self):
        if not self.isValid():
            Exception('Cannot get file because the source file "'+str(self.path)+'" does not exist.')
        f = open(self.path,'rU')
        return f

    def save(self,targetpath,claim=True):
        if self.path==targetpath: return
        (sourcepath,sourcename) = os.path.split(self.path)
        print 'Copying "%s".' % sourcename
        shutil.copyfile(self.path,targetpath)
        if claim: self.path=targetpath

    def addToZip(self,zfile,filename):
        if not self.isValid():
            raise Exception('Cannot add "'+filename+'" to zip archive because the source file "'+str(self.path)+'" does not exist.')
        zfile.write(self.path,filename)
            
# TypedXMLPropertyStore: encapsulates the above XMLPropertyStore.
#   Adds the use of a second XML document (template) that describes the data types
#   of the nodes of the first DOM, and that describes dependencies between nodes.
#   Any node in the original document for which conditions are not met is hidden.
#   Nodes that are not described by the template are not allowed in the property store.
#   Node are obtained by traversing the tree (start: TypedXMLPropertyStore.root).
class TypedXMLPropertyStore:

    class Node:
        def __init__(self,controller,templatenode,valuenode,location,parent):
            self.controller = controller
            self.store = controller.store
            self.templatenode = templatenode
            self.valuenode = valuenode
            self.location = location
            self.parent = parent
            self.children = []
            self.futureindex = None
            self.visible = (not self.templatenode.hasAttribute('hidden'))

            for templatechild in self.templatenode.childNodes:
                if templatechild.nodeType==templatechild.ELEMENT_NODE and (templatechild.localName=='variable' or templatechild.localName=='folder'):
                    childloc = self.location[:] + [templatechild.getAttribute('id')]
                    if templatechild.hasAttribute('maxoccurs'):
                        maxoccurs = int(templatechild.getAttribute('maxoccurs'))
                        valuechildren = findDescendantNodes(self.store.xmlroot,childloc)
                        childcount = 0
                        for valuechild in valuechildren:
                            if childcount==maxoccurs:
                                raise Exception('Number of children is greater than the imposed maximum ('+str(maxoccurs)+').')
                            self.children.append(TypedXMLPropertyStore.Node(self.controller,templatechild,valuechild,childloc,parent=self))
                            childcount += 1
                    else:
                        valuechild = findDescendantNode(self.store.xmlroot,childloc)                            
                        self.children.append(TypedXMLPropertyStore.Node(self.controller,templatechild,valuechild,childloc,parent=self))

        def __str__(self):
            return str(self.location)

        def destroy(self):
            for ch in self.children:
                if ch!=None: ch.destroy()
            self.location = []
            self.children = []
            self.parent = None
            self.templatenode = None
            self.valuenode = None
            self.store = None

        def setValue(self,value):
            if value==None:
                self.clearValue()
                return

            # If the changed node is of type "file", create a local copy of it.
            valuetype = self.templatenode.getAttribute('type')
            if (not self.controller.suppressautofilecopy) and valuetype=='file':
                datafile = value
                filename = self.getId()+'.dat'
                if not self.isHidden() and datafile.isValid():
                    # Only actually copy the file if the node is currently visible.
                    tmpdir = self.controller.getTempDir()
                    targetpath = os.path.join(tmpdir,filename)
                    datafile.save(targetpath)
                value = filename
            
            curval = self.getValue()
            if curval!=value:
                if self.controller.onBeforeChange(self,value):
                    if self.valuenode==None:
                        self.valuenode = findDescendantNode(self.store.xmlroot,self.location[:],create=True)
                        if self.valuenode==None: raise Exception('unable to create value node at '+str(self.location))
                    changed = self.store.setNodeProperty(self.valuenode,value)
                    self.controller.onChange(self)
                    return changed
            return False

        def getValue(self):
            if self.valuenode==None: return None
            valuetype = self.templatenode.getAttribute('type')
            value = self.store.getNodeProperty(self.valuenode,valuetype=valuetype)
            if valuetype=='file':
                if self.controller.tempdir!=None:
                    datafile = DataFile(os.path.join(self.controller.tempdir,value))
                else:
                    datafile = DataFile()
                return datafile
            return value

        def addChild(self,childname):
            index = -1
            templatenode = None

            # First see of already one instance of this child is in the tree; that makes finding the position easy.
            curindex = 0
            for child in self.children:
                curindex += 1
                if child.location[-1]==childname:
                    index = curindex
                    templatenode = child.templatenode
                elif index!=-1:
                    break

            # The child is not yet in the tree; find the position where to insert the child.
            if index==-1:
                predecessors = []
                for templatechild in self.templatenode.childNodes:
                    if templatechild.nodeType==templatechild.ELEMENT_NODE and (templatechild.localName=='variable' or templatechild.localName=='folder'):
                        childid = templatechild.getAttribute('id')
                        if childid==childname:
                            templatenode = templatechild
                            break
                        predecessors.append(childid)
                index = 0
                for child in self.children:
                    curname = child.location[-1]
                    while len(predecessors)>0 and curname!=predecessors[0]:
                        predecessors.pop(0)
                    if len(predecessors)==0:
                        break
                    else:
                        index += 1

            if templatenode==None: return None

            # Create child node
            location = self.location + [childname]
            valuenode = addDescendantNode(self.store.xmlroot,location)
            child = TypedXMLPropertyStore.Node(self.controller,templatenode,valuenode,location,parent=self)
            if not child.canHaveClones():
                raise Exception('Cannot add another child "'+childname+'" because there must exist only one child with this name.')
            child.futureindex = index
            self.controller.beforeVisibilityChange(child,True,False)
            self.children.insert(index,child)
            self.controller.afterVisibilityChange(child,True,False)
            child.futureindex = None
            return child

        def getNumberedChild(self,childname,index):
            children = self.getLocationMultiple([childname])
            if index<len(children): return children[index]
            for ichild in range(index-len(children)+1):
                child = self.addChild(childname)
            return child

        def removeChildren(self,childname,first=0,last=None):
            ipos = 0
            ichildpos = -1
            while ipos<len(self.children):
                child = self.children[ipos]
                if child.location[-1]==childname:
                    if not child.canHaveClones():
                        raise Exception('Cannot remove child "'+childname+'" because it has to occur exactly one time.')
                    ichildpos += 1
                    if last!=None and ichildpos>last: return
                    if ichildpos>=first:
                        self.controller.beforeVisibilityChange(child,False,False)
                        child = self.children.pop(ipos)
                        self.store.clearNodeProperty(child.valuenode)
                        self.controller.afterVisibilityChange(child,False,False)
                        ipos -= 1
                ipos += 1

        def removeAllChildren(self):
            ipos = 0
            while ipos<len(self.children):
                child = self.children[ipos]
                if child.canHaveClones():
                    self.controller.beforeVisibilityChange(child,False,False)
                    child = self.children.pop(ipos)
                    self.store.clearNodeProperty(child.valuenode)
                    self.controller.afterVisibilityChange(child,False,False)
                else:
                    ipos += 1

        def clearValue(self):
            if self.valuenode==None: return
            if self.controller.onBeforeChange(self,None):
                self.store.clearNodeProperty(self.valuenode)
                self.valuenode = None
                self.controller.onChange(self)

        def getId(self):
            return self.templatenode.getAttribute('id')

        def getValueType(self):
            return self.templatenode.getAttribute('type')

        def getDescription(self,idallowed = False):
            templatenode = self.templatenode
            if templatenode.hasAttribute('description'):
                return templatenode.getAttribute('description')
            elif templatenode.hasAttribute('label'):
                return templatenode.getAttribute('label')
            elif idallowed:
                return self.getId()
            return None

        def getChildCount(self,showhidden=False):
            if showhidden: return len(self.children)
            childcount = 0
            for child in self.children:
                if not child.isHidden(): childcount += 1
            return childcount

        def getChildren(self,showhidden=False):
            if showhidden: return self.children
            res = []
            for child in self.children:
                if not child.isHidden(): res.append(child)
            return res

        def getChildByIndex(self,index,showhidden=False):
            if showhidden: return self.children[index]
            curindex = 0
            for child in self.children:
                if not child.isHidden():
                    if curindex==index: return child
                    curindex += 1
            raise Exception('Could not find child number '+str(index))

        def getOwnIndex(self,showhidden=False):
            offspring = self.parent.children
            irow = 0
            if self.futureindex!=None:
                if showhidden: return self.futureindex
                else:
                    irow = 0
                    for isibling in range(self.futureindex):
                        if not offspring[isibling].isHidden(): irow += 1
                    return irow
            else:
                for child in offspring:
                    if child is self: return irow
                    if showhidden or (not child.isHidden()): irow += 1
            raise Exception('Cannot find ourselves in child list of parent.')

        def getLocation(self,location):
            # Get the first non-empty path term.
            path = location[:]
            target = ''
            while target=='' and len(path)>0: target = path.pop(0)
            if target=='': return self

            for child in self.children:
                if child.location[-1]==target:
                    if len(path)==0:
                        return child
                    else:
                        return child.getLocation(path)
            return None

        def getLocationMultiple(self,location):
            # Get the first non-empty path term.
            path = location[:]
            target = ''
            while target=='' and len(path)>0: target = path.pop(0)
            if target=='': return [self]

            res = []
            for child in self.children:
                if child.location[-1]==target:
                    if len(path)==0:
                        res.append(child)
                    else:
                        res += child.getLocationMultiple(path)
            return res

        def isHidden(self):
            node = self
            while node!=None:
                if not node.visible: return True
                node = node.parent
            return False

        def isReadOnly(self):
            return self.templatenode.hasAttribute('readonly')
    
        def isFolder(self):
            templatenode = self.templatenode
            return (templatenode.nodeType==templatenode.ELEMENT_NODE and templatenode.localName=='folder')

        def isVariable(self):
            templatenode = self.templatenode
            return (templatenode.nodeType==templatenode.ELEMENT_NODE and templatenode.localName=='variable')

        def canHaveClones(self):
            return self.templatenode.hasAttribute('maxoccurs')

        def getNodesByType(self,valuetype):
            res = []
            if self.getValueType()==valuetype: res.append(self)
            children = self.getChildren(showhidden=True)
            for ch in children:
                res += ch.getNodesByType(valuetype)
            return res

        def updateVisibility(self,recursive=False):
            templatenode = self.templatenode
            cond = findDescendantNode(templatenode,['condition'])
            if cond!=None:
                showold = self.visible
                shownew = self.controller.checkCondition(cond,templatenode)
                if showold!=shownew:
                    # Visibility of dependent node has changed. Set the new status,
                    # and emit before and after visibility-changed events
                    self.controller.beforeVisibilityChange(self,shownew)
                    self.visible = shownew
                    self.controller.afterVisibilityChange(self,shownew)
            if recursive:
                children = self.getChildren(showhidden=True)
                for child in children:
                    child.updateVisibility(recursive=True)

        def copyFrom(self,sourcenode,replace=True):
            if self.isVariable():
                if replace or self.getValue()==None:
                    self.setValue(sourcenode.getValue())
            elif replace:
                self.removeAllChildren()
            prevchildname = None
            index = 0
            for sourcechild in sourcenode.children:
                childname = sourcechild.location[-1]
                if childname!=prevchildname:
                    index = 0
                    prevchildname = childname
                if sourcechild.canHaveClones():
                    child = self.getNumberedChild(childname,index)
                else:
                    child = self.getLocation([childname])
                if child==None: continue
                child.copyFrom(sourcechild,replace=replace)
                index += 1

    def __init__(self,xmltemplate,xmldocument,xmlroot=None):

        # The template can be specified as a DOM object, or as string (i.e. path to XML file)
        if isinstance(xmltemplate,str):
            xmltemplate = xml.dom.minidom.parse(xmltemplate)
        self.templatedom = xmltemplate
        self.version = self.templatedom.documentElement.getAttribute('version')

        # Set event handlers
        self.visibilityhandlers = []
        self.changehandlers = []
        self.beforechangehandlers = []
        self.storechangedhandlers = []
        self.enableevents = True
        self.suppressConditionChecking = False

        # For every variable: build a list of variables/folders that depend on its value.
        self.buildDependencies()

        # Set property store
        self.store = None
        self.root = None
        self.setStore(xmldocument,xmlroot)

        # Variables that deal with storage of data files the store links to.
        self.tempdir = None
        self.tempdirowner = True
        self.suppressautofilecopy = False
        self.datafiles = {}

    def unlink(self):
        if self.tempdir!=None:
            if self.tempdirowner:
                print 'Deleting temporary directory "'+self.tempdir+'".'
                shutil.rmtree(self.tempdir)
            self.tempdir = None

        if self.root!=None: self.root.destroy()
        self.root = None
        self.store = None
        self.visibilityhandlers = []
        self.changehandlers = []
        self.beforechangehandlers = []
        self.storechangedhandlers = []

    def getTempDir(self,empty=False):
        if self.tempdir!=None:
            if empty and self.tempdirowner:
                for f in os.listdir(self.tempdir): 
                    os.remove(os.path.join(self.tempdir,f))
        else:
            self.tempdir = tempfile.mkdtemp('','gotm-')
            self.tempdirowner = True
            print 'Created temporary property store directory "'+self.tempdir+'".'
        return self.tempdir

    def setStore(self,xmldocument,xmlroot=None):
        if self.root!=None: self.root.destroy()

        templateroot = self.templatedom.documentElement

        if xmldocument==None:
            if xmlroot!=None:
                xmldocument = xmlroot
                while xmldocument.parentNode!=None: xmldocument = xmldocument.parentNode
            else:
                impl = xml.dom.minidom.getDOMImplementation()
                xmldocument = impl.createDocument('', templateroot.getAttribute('id'), None)
                xmldocument.documentElement.setAttribute('version',self.version)

        if xmlroot==None: xmlroot = xmldocument.documentElement
        storeversion = xmlroot.getAttribute('version')
        if storeversion!=self.version:
            raise Exception('Versions of the xml template and and the xml values do not match.')
                    
        self.store = XMLPropertyStore(xmldocument,xmlroot=xmlroot)
        self.store.filetypes['select'] = int
        self.store.filetypes['file'] = str
        self.root = TypedXMLPropertyStore.Node(self,templateroot,self.store.xmlroot,[],None)
        if not self.suppressConditionChecking: self.updateVisibility()
        self.changed = False

        self.afterStoreChange()

    def hasChanged(self):
        return self.changed

    def resetChanged(self):
        self.changed = False

    def setProperty(self,location,value):
        node = self.root.getLocation(location)
        if node==None: raise Exception('Cannot locate node at '+str(location))
        return node.setValue(value)
    
    def getProperty(self,location):
        node = self.root.getLocation(location)
        if node==None: raise Exception('Cannot locate node at '+str(location))
        return node.getValue()

    # suppressVisibilityUpdates: de-activates or re-activates dynamic re-checking of node-conditions
    #   when other nodes change (for performance gains only).
    def suppressVisibilityUpdates(self,sup):
        if self.suppressConditionChecking==sup: return
        if not sup: self.updateVisibility()
        self.suppressConditionChecking = sup

    # buildDependencies: for every variable node, this creates lists of dependent nodes
    # (i.e. folders and variables that have one or more conditions that depend on the
    # variable under investigation). Essentially we convert lists of dependencies ('servant'-centric)
    # into lists of dependent nodes ('controller'-centric). We need the latter in order to selectively
    # re-check conditions (and hide/show corresponding nodes) after the value of
    # a dependency ('controller') changes.
    def buildDependencies(self,root=None,curpath='',curowner=None):
        if root==None: root=self.templatedom.documentElement
        for ch in root.childNodes:
            if ch.nodeType==ch.ELEMENT_NODE:
                if ch.localName=='variable' or ch.localName=='folder':
                    self.buildDependencies(root=ch,curpath=curpath+'/'+ch.getAttribute('id'),curowner=ch)
                elif ch.localName=='condition':
                    if ch.hasAttribute('variable'):
                        deppath = ch.getAttribute('variable').split('/')
                        if deppath[0]=='.':
                            dep = self.getTemplateNode(deppath[1:],root=curowner.parentNode)
                        else:
                            dep = self.getTemplateNode(deppath[:])
                        if dep==None: raise 'checkCondition: cannot locate variable with path "' + str(ch.getAttribute('variable')) + '".'
                        deplist = findDescendantNode(dep,['dependentvariables'],create=True)
                        node = self.templatedom.createElementNS(deplist.namespaceURI,'dependentvariable')
                        node.setAttribute('path',curpath)
                        deplist.appendChild(node)
                    self.buildDependencies(root=ch,curpath=curpath,curowner=curowner)

    # updateVisibility: this checks all conditions on variable and folder nodes, and adds
    # the "hidden" attribute to those nodes if their root condition is not met.
    # This is done only on start-up; after that, conditions are checked selectively after
    # nodes appearing in those conditions change value.
    def updateVisibility(self):
        self.root.updateVisibility(recursive=True)

    # checkCondition: checks whether then given condition (an XML node in the template) is currently met.
    #   "nodeCondition" is the "condition" XML node to check
    #   "ownernode" is the "variable" or "folder" XML node that 'owns' the condition
    #       (= the first ancestor that is not a condition itself)
    def checkCondition(self,nodeCondition,ownernode):
        if not nodeCondition.hasAttribute('type'):
            raise Exception('condition lacks "type" attribute in XML scenario template')
        condtype = nodeCondition.getAttribute('type')
        if condtype=='eq' or condtype=='ne':
            # Check for required XML attributes
            if not nodeCondition.hasAttribute('variable'):
                raise Exception('condition lacks "variable" attribute in XML scenario template')
            if not nodeCondition.hasAttribute('value'):
                raise Exception('condition lacks "value" attribute in XML scenario template')

            # Get path specification for the vairbale we depend on (split on slashes)
            valuepath = nodeCondition.getAttribute('variable').split('/')
            
            if valuepath[0]=='.':
                # First path component = '.': we got relative path for the variable we depend on.
                # Note: this path is now relative to our *parent*, not to us!

                # Get absolute path specification
                valuepath = self.getTemplateNodePath(ownernode.parentNode)+valuepath[1:]

            node = self.root.getLocation(valuepath)
            templatenode = node.templatenode
                
            # Ensure that we have found the variable we depend on.
            if templatenode==None: raise 'checkCondition: cannot locate variable with path "' + str(nodeCondition.getAttribute('variable')) + '".'

            # Get type of node to examine
            valuetype = templatenode.getAttribute('type')
            
            # Get the current value of the variable we depend on
            curvalue = node.getValue()

            # If the node in question currently does not have a value, we cannot check the condition; just return 'valid'.
            if curvalue==None: return True

            # Get the reference value we will compare against
            refvalue = self.store.unpackvalue(nodeCondition.getAttribute('value'),valuetype)

            # Compare
            if condtype=='eq': return (curvalue==refvalue)
            if condtype=='ne': return (curvalue!=refvalue)
            
        elif condtype=='and' or condtype=='or':
            # Check every child condition.
            for ch in nodeCondition.childNodes:
                if ch.nodeType==ch.ELEMENT_NODE and ch.localName=='condition':
                    if self.checkCondition(ch,ownernode):
                        # OR query: one True guarantees success 
                        if condtype=='or': return True
                    else:
                        # AND query: one False guarantees failure 
                        if condtype=='and': return False
                        
            # We evaluated all children. If we are doing an OR, that means all
            # children returned False: we failed, if we are doing an AND, all
            # children returned True: we succeeded.
            if condtype=='and': return True
            return False
        else:
            raise 'unknown condition type "' + condtype + '" in XML scenario template'

    # getTemplateNode: obtains template node at given path
    # (path specification consists of array of node ids)
    def getTemplateNode(self,path,root=None):
        if root==None: root=self.templatedom.documentElement
        target = ''
        while target=='' and len(path)>0: target = path.pop(0)
        if target=='' and len(path)==0: return root
        for ch in root.childNodes:
            if ch.nodeType==ch.ELEMENT_NODE and (ch.localName=='folder' or ch.localName=='variable') and ch.getAttribute('id')==target:
                if len(path)==0:
                    return ch
                else:
                    return self.getTemplateNode(path,root=ch)
        return None

    # getNodePath: obtains path specification for given template node
    # (path specification consists of node ids with slash separators)
    def getTemplateNodePath(self,node):
        path = []
        while not node.isSameNode(self.templatedom.documentElement):
            path.insert(0,node.getAttribute('id'))
            node = node.parentNode
        return path

    # onBeforeChange: called internally just before the value of a node changes.
    def onBeforeChange(self,node,newvalue):
        if self.enableevents:
            for callback in self.beforechangehandlers:
                if not callback(node,newvalue): return False
        return True

    # onChange: called internally when the value of a node changes.
    #   Here it is used to dynamically re-check the conditions that depend on the changed node.
    def onChange(self,node):
        # Register that we changed.
        self.changed = True

        # Emit change event
        if self.enableevents:
            for callback in self.changehandlers:
                callback(node)

        # Check if other nodes depend on the changed node, if so, update their visibility.
        if self.suppressConditionChecking: return
        deps = findDescendantNode(node.templatenode,['dependentvariables'])
        if deps==None: return
        for d in deps.childNodes:
            if d.nodeType==d.ELEMENT_NODE and d.localName=='dependentvariable':
                # We found a dependent node; update its visibility
                varpath = d.getAttribute('path').split('/')
                varnode = self.root.getLocation(varpath)
                varnode.updateVisibility()

    def addStoreChangedHandler(self,callback):
        self.storechangedhandlers += [callback]

    def afterStoreChange(self):
        if self.enableevents:
            for callback in self.storechangedhandlers:
                callback()

    def addVisibilityChangeHandler(self,beforecallback,aftercallback):
        self.visibilityhandlers += [[beforecallback,aftercallback]]

    def beforeVisibilityChange(self,node,visible,showhide=True):
        if self.enableevents:
            for callback in self.visibilityhandlers:
                if callback[0]!=None: callback[0](node,visible,showhide)

    def afterVisibilityChange(self,node,visible,showhide=True):
        if self.enableevents:
            for callback in self.visibilityhandlers:
                if callback[1]!=None: callback[1](node,visible,showhide)

    def save(self,path):
        return self.store.save(path)

    def toxml(self,enc):
        return self.store.xmldocument.toxml(enc)

    def toxmldom(self):
        return self.store.xmldocument.cloneNode(True)

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # addChangeHandler: registers a callback, to be called when a property changes value.
    def addChangeHandler(self,callback):
        self.changehandlers += [callback]

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # addBeforeChangeHandler: registers a callback, to be called just before a property would
    #    change value. the change is approved if the callback return True, and rejected if it
    #    returns False.
    def addBeforeChangeHandler(self,callback):
        self.beforechangehandlers += [callback]

    # =========================================================================================
    # PUBLIC
    # =========================================================================================
    # enableEvents: enables/disables sending of change-events.
    def enableEvents(self,enabled):
        self.enableevents = enabled

class Scenario(TypedXMLPropertyStore):

    templates = None
    
    def __init__(self,xmltemplate=None,xmldocument=None,templatename=None):
        if templatename!=None:
            # If the specified scenario is the id of a template, fill in the path to the template file
            tmpls = Scenario.getTemplates()
            if templatename in tmpls:
                xmltemplate = tmpls[templatename]
            else:
                raise Exception('Unable to locate template XML file for specified scenario version "'+templatename+'".')
        elif xmltemplate==None:
            raise Exception('No scenario template specified. Either specify a file, or a name or a template (as "templatename").')
        elif not os.path.isfile(xmltemplate):
            raise Exception('Scenario template "'+xmltemplate+'" does not exist.')

        TypedXMLPropertyStore.__init__(self,xmltemplate,xmldocument)

    @staticmethod
    def getTemplates():
        if Scenario.templates==None:
            Scenario.templates = {}
            templatedir = os.path.join(os.path.dirname(__file__),'scenariotemplates')
            if os.path.isdir(templatedir):
                for templatename in os.listdir(templatedir):
                    fullpath = os.path.join(templatedir,templatename)
                    if os.path.isfile(fullpath):
                        (root,ext) = os.path.splitext(templatename)
                        if ext=='.xml':
                            Scenario.templates[root] = fullpath
                        else:
                            print 'WARNING: template directory contains non-XML file "%s"; this file will be ignored.' % templatename
            else:
                print 'WARNING: no templates will be available, because subdir "scenariotemplates" is not present!'
        return Scenario.templates

    @staticmethod
    def fromNamelists(path,protodir=None,targetversion=None):
        if targetversion==None: targetversion=guiscenarioversion
        
        templates = Scenario.getTemplates()
        sourceids = scenarioformats.rankSources(targetversion,templates.keys(),requireplatform='gotm')
        scenario = None
        failures = ''
        for sourceid in sourceids:
            print 'Trying scenario format "'+sourceid+'"...'
            scenario = Scenario(templatename=sourceid)
            try:
                scenario.loadFromNamelists(path,requireordered = True,protodir=protodir)
            except Scenario.NamelistParseException,e:
                failures += 'Path "'+path+'" does not match template "'+sourceid+'".\nReason: '+str(e)+'\n'
                scenario.unlink()
                scenario = None
            if scenario!=None:
                #print 'Path "'+path+'" matches template "'+template+'".'
                break
        if scenario==None:
            raise Exception('The path "'+path+'" does not contain a supported GOTM scenario. Details:\n'+failures)
        if scenario.version!=targetversion:
            newscenario = scenario.convert(targetversion)
            scenario.unlink()
            return newscenario
        else:
            return scenario

    def convert(self,target,targetownstemp=True):        
        if isinstance(target,str):
            target = Scenario(templatename=target)
        
        convertor = scenarioformats.getConvertor(self.version,target.version)
        convertor.targetownstemp = targetownstemp
        if convertor==None:
            raise Exception('No convertor available to convert version "'+self.version+'" into "'+target.version+'".')
        convertor.convert(self,target)

        return target

    class NamelistParseException(Exception):
        def __init__(self,error,filename=None,namelistname=None,variablename=None):
            Exception.__init__(self,error)
            self.filename     = filename
            self.namelistname = namelistname
            self.variablename = variablename

        def __str__(self):
            return Exception.__str__(self)+'.\nFile: '+str(self.filename)+', namelist: '+str(self.namelistname)+', variable: '+str(self.variablename)

    def loadFromNamelists(self, srcpath, requireordered = False, protodir = None):
        print 'Importing scenario from namelist files...'

        # Start with empty scenario
        self.setStore(None,None)

        nmltempdir = None
        if not os.path.isdir(srcpath):
            if os.path.isfile(srcpath):
                try:
                    tf = tarfile.open(srcpath,'r')
                except Exception,e:
                    print e
                    raise Exception('Path "'+srcpath+'" is not a directory, and could also not be opened as tar/gz archive. '+str(e))
                nmltempdir = tempfile.mkdtemp('','gotm-')
                print 'Created temporary namelist directory "'+nmltempdir+'".'
                for tarinfo in tf:
                    tf.extract(tarinfo,nmltempdir)
                tf.close()
                srcpath = nmltempdir
                extracteditems = os.listdir(srcpath)
                if len(extracteditems)==1:
                    itempath = os.path.join(srcpath,extracteditems[0])
                    if os.path.isdir(itempath):
                        srcpath = itempath
            else:
                raise Exception('Path "'+srcpath+'" is not an existing directory or file.')

        if protodir!=None:
            valuesubs = []
            regexpre = re.compile('s/(\w+)/(.+)/')
            valuespath = os.path.join(srcpath,os.path.basename(srcpath)+'.values')
            try:
                valuesfile = open(valuespath,'rU')
            except Exception,e:
                raise self.NamelistParseException('Cannot open .values file. Error: '+str(e))
            line = valuesfile.readline()
            while line!='':
                m = regexpre.match(line)
                if m!=None:
                    valuesubs.append((re.compile(m.group(1)),m.group(2)))
                line = valuesfile.readline()
            valuesfile.close()

        try:
            for mainchild in self.root.getChildren(showhidden=True):
                if not mainchild.isFolder():
                    raise Exception('Found non-folder node with id '+mainchild.getId()+' below root, where only folders are expected.')

                # Get name (excl. extension) for the namelist file, and its full path.
                nmlfilename = mainchild.getId()

                if protodir==None:
                    nmlfilepath = os.path.join(srcpath, nmlfilename+'.inp')
                else:
                    nmlfilepath = os.path.join(protodir, nmlfilename+'.proto')

                # Attempt to open namelist file and read all data
                try:
                    nmlfile = open(nmlfilepath,'rU')
                except Exception,e:
                    if mainchild.isHidden(): continue
                    raise self.NamelistParseException('Cannot open namelist file. Error: '+str(e),nmlfilepath)
                nmldata = nmlfile.read()
                nmlfile.close()

                if protodir!=None:
                    for (exp,repl) in valuesubs:
                        nmldata = exp.sub(repl,nmldata)

                # Strip comments, i.e. on every line, remove everything after (and including) the first exclamation mark
                commentre = re.compile('![^\n]*')
                nmldata = commentre.sub('',nmldata)
                
                listre = re.compile('\s*&\s*(\w+)\s*(.*?)\s*/\s*',re.DOTALL)
                strre = re.compile('^[\'"](.*?)[\'"]$')
                datetimere = re.compile('(\d\d\d\d)[/\-](\d\d)[/\-](\d\d) (\d\d):(\d\d):(\d\d)')

                for filechild in mainchild.getChildren(showhidden=True):
                    if not filechild.isFolder():
                        raise 'Found non-folder node with id '+filechild.getId()+' below branch '+nmlfilename+', where only folders are expected.'

                    listname = filechild.getId()
                    #match = listre.match(nmldata)
                    #if match==None:
                    #    raise self.NamelistParseException('Cannot find another namelist, while expecting namelist '+listname+'.',nmlfilepath,listname)
                    (foundlistname,listdata,nmldata) = readNamelist(nmldata)
                    #foundlistname = match.group(1)
                    #listdata = match.group(2)
                    #nmldata = nmldata[len(match.group(0)):]
                    if foundlistname!=listname:
                        raise self.NamelistParseException('Expected namelist '+listname+', but found '+foundlistname+'.',nmlfilepath,listname)
                        
                    for listchild in filechild.getChildren(showhidden=True):
                        if not listchild.isVariable():
                            raise 'Found non-variable node with id '+listchild.getId()+' below branch '+nmlfilename+'/'+listname+', where only variables are expected.'

                        varname = listchild.getId()
                        vartype = listchild.getValueType()

                        if requireordered:
                            varmatch = re.match('\s*'+varname+'\s*=\s*(.*?)[ \t]*(?:$|(?:[,\n]\s*))',listdata,re.IGNORECASE)
                        else:
                            varmatch = re.search('(?<!\w)'+varname+'\s*=\s*(.*?)[ \t]*(?:$|(?:[,\n]))',listdata,re.IGNORECASE)
                        if varmatch==None:
                            raise self.NamelistParseException('Cannot find variable ' + varname + '. Current namelist data: "'+listdata+'"',nmlfilepath,listname,varname)
                        vardata = varmatch.group(1)
                        if requireordered: listdata = listdata[len(varmatch.group(0)):]

                        if vartype=='string' or vartype=='datetime' or vartype=='file':
                            strmatch = strre.match(vardata)
                            if strmatch==None:
                                raise self.NamelistParseException('Variable is not a string. Data: "'+vardata+'"',nmlfilepath,listname,varname)
                            val = strmatch.group(1)
                        elif vartype=='int':
                            try:
                                val = int(vardata)
                            except:
                                raise self.NamelistParseException('Variable is not an integer. Data: "'+vardata+'"',nmlfilepath,listname,varname)
                        elif vartype=='float':
                            try:
                                val = float(vardata)
                            except:
                                raise self.NamelistParseException('Variable is not a floating point value. Data: "'+vardata+'"',nmlfilepath,listname,varname)
                        elif vartype=='bool':
                            if   vardata[0].lower()=='f' or vardata[0:2].lower()=='.f':
                                val = False
                            elif vardata[0].lower()=='t' or vardata[0:2].lower()=='.t':
                                val = True
                            else:
                                raise self.NamelistParseException('Variable is not a boolean. Data: "'+vardata+'"',nmlfilepath,listname,varname)
                        elif vartype=='select':
                            try:
                                val = int(vardata)
                            except:
                                raise self.NamelistParseException('Variable is not an integer. Data: "'+vardata+'"',nmlfilepath,listname,varname)
                        else:
                            raise 'Unknown variable type '+str(vartype)+' in scenario template.'
                        
                        if vartype=='datetime':
                            datetimematch = datetimere.match(val)
                            if datetimematch==None:
                                raise self.NamelistParseException('Variable is not a date + time. String contents: "'+val+'"',nmlfilepath,listname,varname)
                            refvals = map(lambda(i): int(i),datetimematch.group(1,2,3,4,5,6)) # Convert matched strings into integers
                            val = datetime.datetime(*refvals)
                        elif vartype=='file':
                            # Make absolute path
                            filepath = os.path.normpath(os.path.join(os.getcwd(),srcpath, val))
                            val = DataFile(filepath)

                        listchild.setValue(val)
        finally:
            if nmltempdir!=None:
                print 'Removing temporary namelist directory "'+nmltempdir+'".'
                shutil.rmtree(nmltempdir)

    def writeAsNamelists(self, targetpath, copydatafiles=True, addcomments = False):
        print 'Exporting scenario to namelist files...'

        # If the directory to write to does not exist, create it.
        if (not os.path.isdir(targetpath)):
            try:
                os.mkdir(targetpath)
            except Exception,e:
                raise Exception('Unable to create target directory "'+targetpath+'". Error: '+str(e))

        if addcomments:
            # Import and configure text wrapping utility.
            import textwrap
            linelength = 80
            wrapper = textwrap.TextWrapper(subsequent_indent='  ')
        
        for mainchild in self.root.getChildren(showhidden=True):
            if not mainchild.isFolder():
                raise Exception('Found a variable below the root node, where only folders are expected.')
            if mainchild.isHidden(): continue

            nmlfilename = mainchild.getId()
            nmlfilepath = os.path.join(targetpath, nmlfilename+'.inp')
            nmlfile = open(nmlfilepath,'w')

            for filechild in mainchild.getChildren(showhidden=True):
                if not filechild.isFolder():
                    raise Exception('Found a variable directly below branch '+str(nmlfilename)+', where only folders are expected.')
                listname = filechild.getId()

                if addcomments:
                    nmlfile.write('!'+(linelength-1)*'-'+'\n')
                    title = filechild.getDescription(idallowed=True).encode('ascii','xmlcharrefreplace')
                    nmlfile.write(textwrap.fill(title,linelength-2,initial_indent='! ',subsequent_indent='! '))
                    nmlfile.write('\n!'+(linelength-1)*'-'+'\n')

                    comments = []
                    varnamelength = 0
                    for listchild in filechild.getChildren(showhidden=True):
                        comment = self.getNamelistVariableDescription(listchild)
                        if len(comment[0])>varnamelength: varnamelength = len(comment[0])
                        comments.append(comment)
                    wrapper.width = linelength-varnamelength-5
                    for (varid,vartype,lines) in comments:
                        wrappedlines = []
                        lines.insert(0,'['+vartype+']')
                        for line in lines:
                            line = line.encode('ascii','xmlcharrefreplace')
                            wrappedlines += wrapper.wrap(line)
                        firstline = wrappedlines.pop(0)
                        nmlfile.write('! %-*s %s\n' % (varnamelength,varid,firstline))
                        for line in wrappedlines:
                            nmlfile.write('! '+varnamelength*' '+'   '+line+'\n')
                    if len(comments)>0:
                        nmlfile.write('!'+(linelength-1)*'-'+'\n')
                    nmlfile.write('\n')

                nmlfile.write('&'+listname+'\n')
                for listchild in filechild.getChildren(showhidden=True):
                    if not listchild.isVariable():
                        raise Exception('Found a folder ('+str(listchild.getId())+') below branch '+str(nmlfilename)+'/'+str(listname)+', where only variables are expected.')
                    varname = listchild.getId()
                    vartype = listchild.getValueType()
                    varval = listchild.getValue()
                    if varval==None:
                        raise Exception('Value for variable "'+varname+'" in namelist "'+listname+'" not set.')
                    if vartype=='string':
                        varval = '\''+varval+'\''
                    elif vartype=='file':
                        filename = listchild.getId()+'.dat'
                        if not listchild.isHidden() and copydatafiles:
                            varval.save(os.path.join(targetpath,filename),claim=False)
                        varval = '\''+filename+'\''
                    elif vartype=='int' or vartype=='select':
                        varval = str(varval)
                    elif vartype=='float':
                        varval = str(varval)
                    elif vartype=='bool':
                        if varval:
                            varval = '.true.'
                        else:
                            varval = '.false.'
                    elif vartype=='datetime':
                        varval = '\''+varval.strftime('%Y-%m-%d %H:%M:%S')+'\''
                    else:
                        raise Exception('Unknown variable type '+str(vartype)+' in scenario template.')
                    nmlfile.write('   '+varname+' = '+varval+',\n')
                nmlfile.write('/\n\n')

            nmlfile.close()

    @staticmethod
    def getNamelistVariableDescription(node):
        varid = node.getId()
        datatype = node.getValueType()
        description = node.getDescription(idallowed=True)
        lines = [description]
        
        if datatype == 'select':
            # Create list of options.
            options = findDescendantNode(node.templatenode,['options'])
            if options==None: raise 'Node is of type "select" but lacks "options" childnode.'
            for ch in options.childNodes:
                if ch.nodeType==ch.ELEMENT_NODE and ch.localName=='option':
                    lab = ch.getAttribute('description')
                    if lab=='': lab = ch.getAttribute('label')
                    lines.append(ch.getAttribute('value') + ': ' + lab)

        # Create description of data type and range.
        if datatype=='file':
            datatype = 'file path'
        elif datatype=='int' or datatype=='select':
            datatype = 'integer'
        elif datatype=='datetime':
            datatype = 'string, format = "yyyy-mm-dd hh:mm:ss"'
        if node.templatenode.hasAttribute('minimum'):
            datatype += ', minimum = ' + node.templatenode.getAttribute('minimum')
        if node.templatenode.hasAttribute('maximum'):
            datatype += ', maximum = ' + node.templatenode.getAttribute('maximum')
        if node.templatenode.hasAttribute('unit'):
            datatype += ', unit = ' + node.templatenode.getAttribute('unit')

        # Get description of conditions (if any).
        condition = findDescendantNode(node.templatenode,['condition'])
        if condition!=None:
            condline = Scenario.getNamelistConditionDescription(condition)
            lines.append('This variable is used only if '+condline)

        return (varid,datatype,lines)

    @staticmethod
    def getNamelistConditionDescription(node):
        condtype = node.getAttribute('type')
        if condtype=='eq' or condtype=='ne':
            var = node.getAttribute('variable')
            val = node.getAttribute('value')
            if var.startswith('./'): var=var[2:]
            if condtype=='eq':
                return var+' = '+val
            else:
                return var+' != '+val
        elif condtype=='and' or condtype=='or':
            conds = findDescendantNodes(node,['condition'])
            conddescs = map(Scenario.getNamelistConditionDescription,conds)
            return '('+(' '+condtype+' ').join(conddescs)+')'
        else:
            raise Exception('Unknown condition type "%s".' % condtype)

    def saveAll(self,path,targetversion=None,targetisdir = False):
        if targetversion==None: targetversion = savedscenarioversion
        if self.version!=targetversion:
            tempscenario = self.convert(targetversion,targetownstemp=False)
            tempscenario.saveAll(path,targetversion=targetversion)
            tempscenario.unlink()
        else:
            if targetisdir:
                # If the directory to write to does not exist, create it.
                if (not os.path.isdir(path)):
                    try:
                        os.mkdir(path)
                    except Exception,e:
                        raise Exception('Unable to create target directory "'+path+'". Error: '+str(e))
                self.save(os.path.join(path,'scenario.xml'))
            else:
                zfile = zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)
                zfile.writestr('scenario.xml', self.toxml('utf-8'))

            filenodes = self.root.getNodesByType('file')
            for fn in filenodes:
                if not fn.isHidden():
                    filename = str(fn.getId()+'.dat')
                    datafile = fn.getValue()
                    if targetisdir:
                        datafile.save(os.path.join(path,filename),claim=False)
                    else:
                        print 'Adding "'+filename+'" to archive...'
                        datafile.addToZip(zfile,filename)
            if not targetisdir: zfile.close()
        
        self.resetChanged()

    def loadAll(self,path):
        # Basic check: does the specified source path exist?
        if not os.path.exists(path):
            raise Exception('Source path "'+path+'" does not exist.')

        # The specified source file may be a ZIP archive, or a directory that contains the extracted
        # contents of such an archive; decide which.
        srcisdir = os.path.isdir(path)

        if srcisdir:
            # Get list of files in source directory.
            files = os.listdir(path)
        else:
            # Open the archive, and get list of members.
            zfile = zipfile.ZipFile(path,'r')
            files = zfile.namelist()

        # Check for existence of main scenario file.
        if 'scenario.xml' not in files:
            raise Exception('The specified source does not contain "scenario.xml"; it cannot contain a GOTM scenario.')

        # Read and parse the scenario file.
        if not srcisdir:
            scenariodata = zfile.read('scenario.xml')
            storedom = xml.dom.minidom.parseString(scenariodata)
        else:
            storedom = xml.dom.minidom.parse(os.path.join(path,'scenario.xml'))
        
        # Get the scenario version
        version = storedom.documentElement.getAttribute('version')
        if version=='':
            # Unsupported
            print Exception('This is an unversioned scenario created with a gotm-gui alpha. These are no longer supported; please recreate your scenario with the current gotm-gui.')
        if self.version!=version:
            # The version of the saved scenario does not match the version of this scenario object; convert it.
            print 'Scenario "'+path+'" has version "'+version+'"; starting conversion to "'+self.version+'".'
            if not srcisdir: zfile.close()
            tempscenario = Scenario(templatename=version)
            tempscenario.loadAll(path)
            tempscenario.convert(self)
            tempscenario.unlink()

            # If the scenario was stored in the official 'save' version, we should not consider it changed.
            # (even though we had to convert it to the 'display' version). Therefore, reset the 'changed' status.
            if version==savedscenarioversion: self.resetChanged()
        else:
            # Attach the parsed scenario (XML DOM) to ourselves.
            self.setStore(storedom,None)

            # Get all data files that belong to this scenario from the archive.
            tmpdir = self.getTempDir(empty=True)
            filenodes = self.root.getNodesByType('file')
            for fn in filenodes:
                if not fn.isHidden():
                    filename = fn.getId()+'.dat'
                    if filename not in files:
                        raise Exception('The archive "'+path+'" does not contain required data file "'+filename+'".')
                    targetfilepath = os.path.join(tmpdir,filename)
                    if srcisdir:
                        print 'Copying "'+filename+'" to temporary scenario directory...'
                        shutil.copyfile(os.path.join(path,filename),targetfilepath)
                    else:
                        print 'Extracting "'+filename+'" to temporary scenario directory...'
                        filedata = zfile.read(filename)
                        f = open(targetfilepath,'wb')
                        f.write(filedata)
                        f.close()

            # Close the archive
            if not srcisdir: zfile.close()

# Abstract class that contains one or more variables that can be plotted.
# Classes deriving from it must support the virtual methods below.
class PlotVariableStore:

    def __init__(self):
        pass

    def getVariableNames(self):
        return []

    def getVariableLongNames(self):
        varnames = self.getVariableNames()
        vardict = {}
        for name in varnames:
            vardict[name] = self.getVariable(name).getLongName()
        return vardict

    def getVariable(self,varname):
        return None

# Abstract class that represents a variable that can be plotted.
# Classes deriving from it must support the virtual methods below.
class PlotVariable:

    def __init__(self):
        pass

    # getName()
    #   Return type: string
    #   Returns the short name (or identifier) of the variable.
    def getName(self):
        return ''

    # getLongName()
    #   Return type: string
    #   Returns the pretty name for the variable.
    def getLongName(self):
        return ''

    # getUnit()
    #   Return type: string
    #   Returns the unit of the variable.
    def getUnit(self):
        return ''

    # getDimensions()
    #   Return type: tuple of strings
    #   Returns the names of the dimensions of the variable; currently supported dimensions: "time", "z".
    def getDimensions(self):
        return ()

    # getValues(bounds, staggered=False)
    #   Return type: tuple of (numpy/numeric) arrays
    #   Returns the arrays with coordinates (in order of dimnesions returned by getDimensions), and the value array.
    #   Coordinates may be given as 1D arrays (if the coordinates are constant across all other dimensions), or as arrays with
    #   the same numbers of dimensions as the value array (i.e., for every value a coordinate is supplied). If staggered is True,
    #   coordinates must be given at the interfaces and values at the centers; then coordinate arrays must have one extra value in
    #   every dimension compared to the value array.
    def getValues(self,bounds,staggered=False):
        return ()

def findindices(bounds,data):
    # Zero-based indices!
    start = 0
    stop = len(data)-1
    if bounds!=None:
        if bounds[0]!=None:
            while start<len(data) and data[start]<bounds[0]: start+=1
        if bounds[1]!=None:
            while stop>=0         and data[stop] >bounds[1]: stop-=1

        # Greedy: we want take the interval that fully encompasses the specified range.
        # (note that this also corrects for a start beyond the available range, or a stop before it)
        if start>0:          start-=1
        if stop<len(data)-1: stop +=1
        
    return (start,stop)

def interp1(x,y,X):
    if len(x.shape)!=1:
        raise Exception('Original coordinates must be supplied as 1D array.')
    if len(X.shape)!=1:
        raise Exception('New coordinates must be supplied as 1D array.')
    newshape = [X.shape[0]]
    for i in y.shape[1:]: newshape.append(i)
    Y = matplotlib.numerix.zeros(newshape,y.typecode())
    icurx = 0
    for i in range(X.shape[0]):
        while icurx<x.shape[0] and x[icurx]<X[i]: icurx+=1
        if icurx==0:
            Y[i,:] = y[0,:]
        elif icurx>=x.shape[0]:
            Y[i,:] = y[-1,:]
        else:
            rc = (y[icurx,:]-y[icurx-1,:])/(x[icurx]-x[icurx-1])
            Y[i,:] = y[icurx-1,:] + rc*(X[i]-x[icurx-1])
    return Y

class LinkedFileVariableStore(PlotVariableStore):

    class LinkedFileVariable(PlotVariable):

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
            filetype = self.store.type
            if filetype=='profilesintime':
                return ('time','z')
            elif filetype=='pointsintime':
                return ('time',)
            else:
                raise Exception('Cannot plot variables from file of unknown type "'+filetype+'".')

        def getValues(self,bounds,staggered=False):
            data = self.store.getData()
            timebounds = findindices(bounds[0],data[0])
            if len(data)==2:
                return [data[0][timebounds[0]:timebounds[1]+1],data[1][timebounds[0]:timebounds[1]+1,self.index]]
            elif len(data)==3:
                return [data[0][timebounds[0]:timebounds[1]+1],data[1],data[2][timebounds[0]:timebounds[1]+1,:,self.index]]
            else:
                raise Exception('Cannot handle variables with %i dimensions; only know how to deal with 2 or 3 dimensions.' % len(data))

    def __init__(self,node):
        self.vardata = []

        finfo = findDescendantNode(node.templatenode,['fileinfo'])
        self.type = finfo.getAttribute('type')
        
        fvars = findDescendantNode(finfo,['filevariables'])
        if fvars!=None:
            for ch in fvars.childNodes:
                if ch.nodeType==ch.ELEMENT_NODE and ch.localName=='filevariable':
                    longname = ch.getAttribute('label')
                    unit = ch.getAttribute('unit')
                    name = longname
                    self.vardata.append([name,longname,unit])

        self.datafile = node.getValue()
        self.data = None

    def getVariableNames(self):
        varnames = []
        for data in self.vardata:
            varnames.append(data[0])
        return varnames

    def getVariableLongNames(self):
        vardict = {}
        for data in self.vardata:
            vardict[data[0]] = data[1]
        return vardict

    def getVariable(self,varname):
        index = 0
        for data in self.vardata:
            if data[0]==varname:
                return self.LinkedFileVariable(self,data,index)
            index += 1
        raise Exception('Variable with name "%s" not found in store.' % varname)

    def getData(self):
        if self.data!=None: return self.data
        varcount = len(self.vardata)
        
        # Access the data through some read-only file-like object.
        f = self.datafile.getAsReadOnlyFile()

        # Compile regular expression for reading dates.
        datetimere = re.compile('(\d\d\d\d).(\d\d).(\d\d) (\d\d).(\d\d).(\d\d)')

        filetype = self.type
        if filetype=='pointsintime':
            line = f.readline()
            times = []
            values = []
            iline = 1
            while line!='':
                datematch = datetimere.match(line)
                if datematch==None:
                    raise Exception('Line %i does not start with time (yyy-mm-dd hh:mm:ss). Line contents: %s' % (iline,line))
                refvals = map(lambda(i): int(i),datematch.group(1,2,3,4,5,6)) # Convert matched strings into integers
                curdate = datetime.datetime(*refvals)
                data = line[datematch.end()+1:].split()
                if len(data)<varcount:
                    raise Exception('Line %i contains only %i observations, where %i are expected.' % (iline,len(data),varcount))
                data = map(lambda(i): float(i),data)
                times.append(curdate)
                values.append(data)
                line = f.readline()
                iline += 1
            times = matplotlib.numerix.array(times,matplotlib.numerix.PyObject)
            values = matplotlib.numerix.array(values,matplotlib.numerix.Float32)
            self.data = (times,values)
        elif filetype=='profilesintime':
            line = f.readline()
            times = []
            depths = []
            values = []
            uniquedepths = {}
            iline = 1
            while line!='':
                # Read date & time
                datematch = datetimere.match(line)
                if datematch==None:
                    raise Exception('Line %i does not start with time (yyy-mm-dd hh:mm:ss). Line contents: %s' % (iline,line))
                refvals = map(lambda(i): int(i),datematch.group(1,2,3,4,5,6)) # Convert matched strings into integers
                curdate = datetime.datetime(*refvals)

                # Get the number of observations and the depth direction.
                (depthcount,updown) = map(lambda(i): int(i), line[datematch.end()+1:].split())

                # Create arrays that will contains depths and observed values.
                curdepths = matplotlib.numerix.zeros((depthcount,),matplotlib.numerix.Float32)
                curvalues = matplotlib.numerix.zeros((depthcount,varcount),matplotlib.numerix.Float32)
                
                if updown==1:
                    depthindices = range(0,depthcount,1)
                else:
                    depthindices = range(depthcount-1,-1,-1)
                for idepthline in depthindices:
                    line = f.readline()
                    if line=='':
                        raise Exception('Premature end-of-file after line %i; expected %i more observations.' % (iline,depthcount-depthindices.index(idepthline)))
                    iline += 1
                    linedata = map(lambda(i): float(i),line.split())
                    if len(linedata)<varcount+1:
                        raise Exception('Line %i contains only %i value(s), where %i (1 time and %i observations) are expected.' % (iline,len(linedata),varcount+1,varcount))
                    uniquedepths[linedata[0]] = True
                    curdepths[idepthline] = linedata[0]
                    curvalues[idepthline,:] = linedata[1:varcount+1]
                times.append(curdate)
                depths.append(curdepths)
                values.append(curvalues)
                line = f.readline()
                iline += 1
            times = matplotlib.numerix.array(times,matplotlib.numerix.PyObject)
            uniquedepths = uniquedepths.keys()
            uniquedepths.sort()
            depthgrid = matplotlib.numerix.array(uniquedepths,matplotlib.numerix.Float32)
            griddedvalues = matplotlib.numerix.zeros((times.shape[0],depthgrid.shape[0],varcount),matplotlib.numerix.Float32)
            for it in range(len(times)):
                griddedvalues[it,:,:] = interp1(depths[it],values[it],depthgrid)
            self.data = (times,depthgrid,griddedvalues)
        else:
            raise Exception('Cannot plot variables from file of unknown type "'+filetype+'".')
        f.close()
        return self.data

# Class that represents a GOTM result.
#   Inherits from PlotVariableStore, as it contains variables that can be plotted.
#   Contains a link to the scenario from which the result was created (if available)
class Result(PlotVariableStore):

    class ResultVariable(PlotVariable):
        def __init__(self,result,varname):
            PlotVariable.__init__(self)
            self.result = result
            self.varname = str(varname)

        def getName(self):
            return self.varname

        def getLongName(self):
            nc = self.result.getcdf()
            return nc.var(self.varname).long_name

        def getUnit(self):
            nc = self.result.getcdf()
            return nc.var(self.varname).units

        def getDimensions(self):
          nc = self.result.getcdf()
          vars = nc.variables()
          dimnames = vars[self.varname][0]
          dimcount = len(dimnames)
          if   dimcount==3:
              if dimnames==('time','lat','lon'):
                  return ('time',)
          elif dimcount==4:
              if (dimnames==('time','z','lat','lon')) or (dimnames==('time','z1','lat','lon')):
                  return ('time','z')
          else:
            raise Exception('This variable has '+str(dimcount)+' dimensions; I do not know how to handle such variables.')

        def getValues(self,bounds,staggered=False):
          nc = self.result.getcdf()
            
          # Get the variable and its dimensions from CDF.
          try:
              v = nc.var(self.varname)
              dims = v.dimensions()
          except pycdf.CDFError, msg:
              print msg
              return False

          # Get time coordinates and time bounds.
          (t,t_stag) = self.result.getTime()
          timebounds = findindices(bounds[0],t)
          if not staggered:
              t_eff = t[timebounds[0]:timebounds[1]+1]
          else:
              t_eff = t_stag[timebounds[0]:timebounds[1]+2]

          dimcount = len(dims)
          if dimcount==4:
              # Four-dimensional variable: longitude, latitude, depth, time
              try:
                  (z,z1,z_stag,z1_stag) = self.result.getDepth()
                  depthbounds = (0,z.shape[1])
                  if dims[1]=='z':
                      if staggered:
                          z_cur = z_stag[timebounds[0]:timebounds[1]+2,depthbounds[0]:depthbounds[1]+2]
                      else:
                          z_cur = z[timebounds[0]:timebounds[1]+1,depthbounds[0]:depthbounds[1]+1]
                  elif dims[1]=='z1':
                      if staggered:
                          z_cur = z1_stag[timebounds[0]:timebounds[1]+2,depthbounds[0]:depthbounds[1]+2]
                      else:
                          z_cur = z1[timebounds[0]:timebounds[1]+1,depthbounds[0]+1:depthbounds[1]+2]
                  dat = v[timebounds[0]:timebounds[1]+1,depthbounds[0]:depthbounds[1]+1,0,0]
              except pycdf.CDFError, msg:
                  print msg
                  return False
              return [t_eff,z_cur,dat]
          elif dimcount==3:
              # Three-dimensional variable: longitude, latitude, time
              try:
                  dat = v[timebounds[0]:timebounds[1]+1,0,0]
              except pycdf.CDFError, msg:
                  print msg
                  return False
              return [t_eff,dat]
          else:
            raise Exception('This variable has '+str(len(dims))+' dimensions; I do not know how to handle such variables.')

    def __init__(self):
        self.scenario = None
        self.tempdir = None
        self.datafile = None
        self.nc = None
        self.changed = False

        # Cached coordinates
        self.t = None
        self.t_stag = None
        self.z = None
        self.z1 = None
        self.z_stag = None
        self.z1_stag = None

    def getTempDir(self,empty=False):
        if self.tempdir!=None:
            if empty:
                for f in os.listdir(self.tempdir): 
                    os.remove(os.path.join(self.tempdir,f))
        else:
            self.tempdir = tempfile.mkdtemp('','gotm-')
            print 'Created temporary result directory "'+self.tempdir+'".'
        return self.tempdir

    def save(self,path):
        if self.datafile==None:
            raise Exception('The result object was not yet attached to a result file (NetCDF).')

        zfile = zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)

        if self.scenario!=None:
            tempdir = self.getTempDir()
            scenariofile = os.path.join(tempdir,'scenario.gotmscenario')
            self.scenario.saveAll(scenariofile)
            print 'Adding scenario to archive...'
            zfile.write(scenariofile,'scenario.gotmscenario',zipfile.ZIP_STORED)
        
        print 'Adding result to archive...'
        zfile.write(self.datafile,'result.nc')
        
        zfile.close()

        self.changed = False

    def load(self,path):
        # Basic check: does the specified file exist?
        if not os.path.exists(path): raise Exception('File "'+path+'" does not exist.')

        # Open the archive
        zfile = zipfile.ZipFile(path,'r')

        # Get a list of files in the archive, and check whether it contains a scenario and a result.
        files = zfile.namelist()
        if files.count('scenario.gotmscenario')==0:
            raise Exception('The archive "'+path+'" does not contain "scenario.gotmscenario"; it cannot be a GOTM result.')
        if files.count('result.nc')==0:
            raise Exception('The archive "'+path+'" does not contain "result.nc"; it cannot be a GOTM result.')

        # Create a temporary directory to which we can unpack the archive.
        tempdir = self.getTempDir()

        # Unpack the scenario        
        scenariofile = os.path.join(tempdir,'scenario.gotmscenario')
        scenariodata = zfile.read('scenario.gotmscenario')
        f = open(scenariofile,'wb')
        f.write(scenariodata)
        f.close()

        # Unpack the result
        resultfile = os.path.join(tempdir,'result.nc')
        resultdata = zfile.read('result.nc')
        f = open(resultfile,'wb')
        f.write(resultdata)
        f.close()

        # Close the archive
        zfile.close()

        # Load the scenario from file.
        self.scenario = Scenario(templatename=guiscenarioversion)
        self.scenario.loadAll(scenariofile)
        os.remove(scenariofile)

        # Attach the result, try to open the CDF file
        self.datafile = resultfile
        self.getcdf()

        # Reset "changed" status.
        self.changed = False

    def unlink(self):
        if self.nc!=None:
            # Close NetCDF result file.
            self.nc.close()
            self.nc = None
        if self.tempdir!=None:
            # Delete temporary directory.
            print 'Deleting temporary result directory "'+self.tempdir+'".'
            shutil.rmtree(self.tempdir)
            self.tempdir = None

    def attach(self,srcpath,scenario=None):
        self.scenario = scenario
        
        # Create a copy of the result file.
        tempdir = self.getTempDir(empty=True)
        datafile = os.path.join(tempdir,'result.nc')
        shutil.copyfile(srcpath,datafile)

        # Store link to result file, and try to open the CDF file
        self.datafile = datafile
        self.getcdf()

        self.changed = False

    def getcdf(self):
        if self.nc!=None: return self.nc
        if self.datafile==None:
            raise Exception('The result object has not yet been attached to an actual result.')
        try:
          self.nc = pycdf.CDF(str(self.datafile))
        except pycdf.CDFError, e:
            raise Exception('An error occured while opening the NetCDF file "'+self.datafile+'": '+str(e))
        return self.nc

    def getVariableNames(self,plotableonly=True):
        nc = self.getcdf()

        # Get names of NetCDF variables
        try:
          vars = nc.variables()
          if plotableonly:
              # Only take variables with 3 or 4 dimensions
              varNames = []
              for v in vars.keys():
                  dimnames = vars[v][0]
                  dimcount = len(dimnames)
                  if   dimcount==3:
                      if dimnames==('time','lat','lon'):
                          varNames += [v]
                  elif dimcount==4:
                      if (dimnames==('time','z','lat','lon')) | (dimnames==('time','z1','lat','lon')):
                          varNames += [v]
          else:
              # Take all variables
              varNames = vars.keys()

        except pycdf.CDFError, msg:
            raise Exception('CDFError: '+str(msg))

        return varNames

    def getVariableLongNames(self):
      varnames = self.getVariableNames()
      nc = self.getcdf()
      vardict = {}
      for varname in varnames:
          varname_str = str(varname)
          vardict[varname] = nc.var(varname_str).long_name
      return vardict

    def getVariable(self,varname,check=True):
        varname = str(varname)
        if check:
            nc = self.getcdf()
            vars = nc.variables()
            if not (varname in vars): return None
        return self.ResultVariable(self,varname)

    def getTimeRange(self):
      nc = self.getcdf()
      try:
          secs = nc.var('time').get()
      except pycdf.CDFError, msg:
          print msg
          return
      dateref = self.getReferenceDate()
      t1 = dateref + datetime.timedelta(secs[0]/3600/24)
      t2 = dateref + datetime.timedelta(secs[-1]/3600/24)
      return (t1,t2)

    def getDepthRange(self):
      nc = self.getcdf()
      try:
          z  = nc.var('z').get()
          z1 = nc.var('z1').get()
      except pycdf.CDFError, msg:
          print msg
          return
      return (min(z[0],z1[0]),max(z[-1],z1[-1]))

    def getTime(self):
        if self.t==None:
            nc = self.getcdf()

            # Get time coordinate (in seconds since reference date)
            try:
                secs = nc.var('time').get()
            except pycdf.CDFError, msg:
                print msg
                return None
            
            # Convert time-in-seconds to Python datetime objects.
            dateref = self.getReferenceDate()
            t = matplotlib.numerix.zeros((secs.shape[0],),matplotlib.numerix.PyObject)
            for it in range(t.shape[0]):
                t[it] = dateref + datetime.timedelta(secs[it]/3600/24)

            # Create staggered time grid.
            t_stag = matplotlib.numerix.zeros((secs.shape[0]+1,),matplotlib.numerix.PyObject)
            halfdt = datetime.timedelta(seconds=float(secs[1]-secs[0])/2)
            t_stag[0]  = t[0]-halfdt
            t_stag[1:] = t[:]+halfdt
            
            # Cache time grids.
            self.t = t
            self.t_stag = t_stag
            
        return (self.t,self.t_stag)

    def getDepth(self):
        if self.z==None:
            nc = self.getcdf()

            # Get layers heights
            try:
                h = nc.var('h')[:,:,0,0]
            except pycdf.CDFError, msg:
                print msg
                return None
            
            # Get depths of interfaces
            z1 = matplotlib.numerix.cumsum(h[:,:],1)
            z1 = matplotlib.numerix.concatenate((matplotlib.numerix.zeros((z1.shape[0],1),z1.typecode()),z1),1)
            bottomdepth = z1[0,-1]
            z1 = z1[:,:]-bottomdepth

            # Get depth of layer centers
            z = z1[:,1:z1.shape[1]]-0.5*h

            # Interpolate in time to create staggered grid
            z1_med = matplotlib.numerix.concatenate((matplotlib.numerix.take(z1,(0,),0),z1,matplotlib.numerix.take(z1,(-1,),0)),0)
            z_stag = 0.5 * (z1_med[0:z1_med.shape[0]-1,:] + z1_med[1:z1_med.shape[0],:])
            
            z_med = matplotlib.numerix.concatenate((z,matplotlib.numerix.take(z1,(-1,),1)),1)
            z_med = matplotlib.numerix.concatenate((matplotlib.numerix.take(z_med,(0,),0),z_med,matplotlib.numerix.take(z_med,(-1,),0)),0)
            z1_stag = 0.5 * (z_med[0:z_med.shape[0]-1,:] + z_med[1:z_med.shape[0],:])

            self.z = z
            self.z1 = z1
            self.z_stag = z_stag
            self.z1_stag = z1_stag

        return (self.z,self.z1,self.z_stag,self.z1_stag)

    def getplottypes(self,variable):
      nc = self.getcdf()
      variable = str(variable)
      try:
          v = nc.var(variable)
          dims = v.dimensions()
      except pycdf.CDFError, msg:
          print msg
          return
      if len(dims)==4:
          return ('rectangular grid','filled contours')
      elif len(dims)==3:
          return ('default',)
      return

    def getReferenceDate(self):
      # Retrieve reference date/time.
      nc = self.getcdf()
      timeunit = nc.var('time').attr('units').get()
      datematch = re.compile('(\d\d\d\d)[-\/](\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)').search(timeunit, 1)
      if datematch==None:
          print 'Unable to parse "units" attribute of "time" variable in NetCDF file!'
          return False
      refvals = map(lambda(i): int(i),datematch.group(1,2,3,4,5,6)) # Convert matched strings into integers
      dateref = datetime.datetime(*refvals)
      return dateref

class MonthFormatter(matplotlib.dates.DateFormatter):
    def __init__(self):
        matplotlib.dates.DateFormatter.__init__(self,'%b')

    def __call__(self, x, pos=None):
        return matplotlib.dates.DateFormatter.__call__(self,x,pos)[0]

class Figure:

    def __init__(self,figure,properties=None):
        self.figure = figure
        self.canvas = figure.canvas

        # Create empty set of properties (these will combine the 'forced' properties, and the automatically
        # chosen defaults for properties that were not explicitly set).
        self.properties = TypedXMLPropertyStore('figuretemplate.xml',None)
        self.properties.addBeforeChangeHandler(self.onBeforeMergedPropertyChange)
        
        # Create store for the explicitly set properties
        self.forcedproperties = TypedXMLPropertyStore('figuretemplate.xml',properties)
        self.forcedproperties.addChangeHandler(self.onExplicitPropertyChanged)

        self.sources = {}
        self.defaultsource = None
        self.updating = True
        self.haschanged = False

        self.ignorechanges = False

    def setUpdating(self,allowupdates):
        if self.updating != allowupdates:
            self.updating = allowupdates
            if allowupdates and self.haschanged: self.update()

    def onBeforeMergedPropertyChange(self,node,value):
        if self.ignorechanges: return True
        
        # The user tried to modify a figure property; redirect this to the store
        # for explicitly set properties.
        self.forcedproperties.setProperty(node.location,value)

        # Do not allow the change of the merged property store (the changed of
        # the explicit-property-store will force a refresh of the merged properties
        # indirectly).
        return False

    def onExplicitPropertyChanged(self,node):
        self.update()

    def clearSources(self):
        self.sources = {}

    def clearVariables(self):
        self.forcedproperties.root.getLocation(['Data']).removeChildren('Series')
        self.update()

    def clearProperties(self):
        self.forcedproperties.setStore(None)
        self.update()

    def setProperties(self,props):
        self.forcedproperties.setStore(props)
        self.update()

    def getPropertiesCopy(self):
        return self.forcedproperties.toxmldom()

    def addDataSource(self,name,obj):
        self.sources[name] = obj
        if self.defaultsource==None: self.defaultsource = name

    def addVariable(self,varname,source=None):
        datanode = self.forcedproperties.root.getLocation(['Data'])
        series = datanode.addChild('Series')
        series.getLocation(['Variable']).setValue(varname)
        if source!=None:
            series.getLocation(['Source']).setValue(source)
        self.update()

    def update(self):
        if not self.updating:
            self.haschanged = True
            return

        self.figure.clear()

        axes = self.figure.add_subplot(111)

        # Get forced axes boundaries (will be None if not set; then we autoscale)
        tmin = self.forcedproperties.getProperty(['TimeAxis','Minimum'])
        tmax = self.forcedproperties.getProperty(['TimeAxis','Maximum'])
        zmin = self.forcedproperties.getProperty(['DepthAxis','Minimum'])
        zmax = self.forcedproperties.getProperty(['DepthAxis','Maximum'])

        # Variables below will store the effective dimension boundaries
        tmin_eff = None
        tmax_eff = None
        zmin_eff = None
        zmax_eff = None

        # Link between dimension name (e.g., "time","z") and axis (e.g., "x", "y")
        dim2axis = {}

        # We will now adjust the plot properties; disable use of property-change notifications,
        # as those would otherwise call plot.update again, leading to infinite recursion.
        self.ignorechanges = True

        # Shortcuts to the nodes specifying the variables to plot.
        forceddatanode = self.forcedproperties.root.getLocation(['Data'])
        forcedseries = forceddatanode.getLocationMultiple(['Series'])

        # Shortcut to the node that will hold the variables effectively plotted.
        datanode = self.properties.root.getLocation(['Data'])

        # This variable will hold all long names of the plotted variables; will be used to create plot title.
        longnames = []

        iseries = 0
        for forcedseriesnode in forcedseries:
            # Get the name and data source of the variable to plot.
            varname   = forcedseriesnode.getLocation(['Variable']).getValue()
            varsource = forcedseriesnode.getLocation(['Source']).getValue()
            if varsource==None:
                # No data source specified; take default.
                if self.defaultsource==None: raise Exception('No data source set for variable '+varname+', but no default source available either.')
                varsource = self.defaultsource
                
            # Get variable object.
            var = self.sources[varsource].getVariable(varname)
            if var==None: raise Exception('Source "'+varsource+'" does not contain variable with name "'+varname+'".')

            # Copy series information
            newseriesnode = datanode.getNumberedChild('Series',iseries)
            newseriesnode.getLocation(['Variable']).setValue(varname)
            if varsource!=None:
                newseriesnode.getLocation(['Source']).setValue(varsource)

            # Store the variable long name (to be used for building title)
            longnames.append(var.getLongName())

            # Get the (number of) independent dimensions of the current variable.
            dims = var.getDimensions()
            newseriesnode.getLocation(['DimensionCount']).setValue(len(dims))

            # Get the plot type, based on the number of dimensions
            if len(dims)==1:
                plottypenodename = 'PlotType2D'
            elif len(dims)==2:
                plottypenodename = 'PlotType3D'
            else:
                raise Exception('This variable has %i independent dimensions. Can only plot variables with 2 or 3 independent dimensions.' % len(dims))
            plottype = forcedseriesnode.getLocation([plottypenodename]).getValue()
            if plottype==None: plottype=0
            newseriesnode.getLocation([plottypenodename]).setValue(plottype)

            staggered = False
            if plottypenodename=='PlotType3D' and plottype==0: staggered = True

            # Set forced bounds for the different dimensions
            dimbounds = []
            for dimname in dims:
                if dimname=='time':
                    dimbounds.append((tmin,tmax))
                elif dimname=='z':
                    dimbounds.append((zmin,zmax))
                else:
                    raise Exception('Variable has unknown dimension "'+dimname+'".')

            # Get the data
            data = var.getValues(dimbounds,staggered=staggered)

            # Transform to log-scale if needed
            logscale = forcedseriesnode.getLocation(['LogScale']).getValue()
            if logscale==None: logscale = False
            newseriesnode.getLocation(['LogScale']).setValue(logscale)
            if logscale:
                data[-1] = matplotlib.numerix.ma.masked_array(data[-1],data[-1]<=0)
                data[-1] = matplotlib.numerix.ma.log10(data[-1])

            # get label
            label = forcedseriesnode.getLocation(['Label']).getValue()
            if label==None:
                label = var.getLongName()+' ('+var.getUnit()+')'
                if logscale: label = 'log10 '+label
            newseriesnode.getLocation(['Label']).setValue(label)

            for idim in range(len(dims)):
                if len(data[idim].shape)==1:
                    datamin = data[idim][0]
                    datamax = data[idim][-1]
                else:
                    if idim==0:
                        datamin = min(data[idim][0,:])
                        datamax = max(data[idim][-1,:])
                    else:
                        datamin = min(data[idim][:,0])
                        datamax = max(data[idim][:,-1])

                #print dims[idim]+' '+str(data[idim])
                if dims[idim]=='time':
                    # Update effective time bounds
                    if tmin_eff==None or datamin<tmin_eff: tmin_eff=datamin
                    if tmax_eff==None or datamax>tmax_eff: tmax_eff=datamax
                    
                    # Convert time (datetime objects) to time unit used by MatPlotLib
                    data[idim] = matplotlib.dates.date2num(data[idim])
                elif dims[idim]=='z':
                    # Update effective depth bounds
                    if zmin_eff==None or datamin<zmin_eff: zmin_eff=datamin
                    if zmax_eff==None or datamax>zmax_eff: zmax_eff=datamax

            # Plot the data series
            if len(dims)==1:
                # One-dimensional variable; currently this implies dependent on time only.
                xdim = 0

                linewidth = forcedseriesnode.getLocation(['LineWidth']).getValue()
                if linewidth==None: linewidth = .5
                newseriesnode.getLocation(['LineWidth']).setValue(linewidth)

                lines = axes.plot(data[xdim],data[-1],'-',linewidth=linewidth)
                dim2axis[dims[xdim]] = 'x'
                axes.set_ylabel(label)
            elif len(dims)==2:
                # Two-dimensional variable, i.e. dependent on time and depth.
                xdim = 0
                ydim = 1

                dim2axis[dims[xdim]] = 'x'
                dim2axis[dims[ydim]] = 'y'

                X = data[xdim]
                Y = data[ydim]
                Z = data[-1]

                # Get length of coordinate dimensions.
                if len(X.shape)==1:
                    xlength = X.shape[0]
                else:
                    xlength = X.shape[xdim]
                if len(Y.shape)==1:
                    ylength = Y.shape[0]
                else:
                    ylength = Y.shape[ydim]
                
                # Adjust X dimension.
                if len(X.shape)==1:
                    X = matplotlib.numerix.reshape(X,(1,-1))
                    X = matplotlib.numerix.repeat(X, ylength, 0)
                elif xdim<ydim:
                    X = matplotlib.numerix.transpose(X)
                    
                # Adjust Y dimension.
                if len(Y.shape)==1:
                    Y = matplotlib.numerix.reshape(Y,(-1,1))
                    Y = matplotlib.numerix.repeat(Y, xlength, 1)
                elif xdim<ydim:
                    Y = matplotlib.numerix.transpose(Y)
                    
                # Adjust Z dimension.
                if xdim<ydim:
                    # Note: using masked array transpose because values can be masked (e.g. after log-transform)
                    Z = matplotlib.numerix.ma.transpose(Z)

                if plottype==1:
                  pc = axes.contourf(X,Y,Z)
                else:
                  #pc = axes.pcolor(X,Y,Z,shading='flat', cmap=matplotlib.pylab.cm.jet)
                  pc = axes.pcolormesh(X,Y,Z,shading='flat', cmap=matplotlib.pylab.cm.jet)
                  #im.set_interpolation('bilinear')
                cb = self.figure.colorbar(mappable=pc)
                if label!='': cb.set_label(label)

            # Hold all plot properties so we can plot additional data series.
            axes.hold(True)

            iseries += 1

        # Remove unused series (remaining from previous plots that had more data series)
        datanode.removeChildren('Series',first=iseries)

        #axes.autoscale_view()

        # Create and store title
        title = self.forcedproperties.getProperty(['Title'])
        if title==None: title = ', '.join(longnames)
        if title!='': axes.set_title(title)
        self.properties.setProperty(['Title'],title)

        # Store current axes bounds
        if tmin==None: tmin = tmin_eff
        if tmax==None: tmax = tmax_eff
        if zmin==None: zmin = zmin_eff
        if zmax==None: zmax = zmax_eff
        self.properties.setProperty(['TimeAxis', 'Minimum'],tmin)
        self.properties.setProperty(['TimeAxis', 'Maximum'],tmax)
        self.properties.setProperty(['DepthAxis','Minimum'],zmin)
        self.properties.setProperty(['DepthAxis','Maximum'],zmax)

        # Configure time axis (x-axis), if any.
        if 'time' in dim2axis:
            timeaxis = dim2axis['time']
            
            # Obtain label for time axis.
            tlabel = self.forcedproperties.getProperty(['TimeAxis','Label'])
            if tlabel==None: tlabel = 'time'
            self.properties.setProperty(['TimeAxis', 'Label'],tlabel)

            # Configure limits and label of time axis.
            if timeaxis=='x':
                taxis = axes.xaxis
                if tlabel!='': axes.set_xlabel(tlabel)
                axes.set_xlim(matplotlib.dates.date2num(tmin),matplotlib.dates.date2num(tmax))
            elif timeaxis=='y':
                taxis = axes.yaxis
                if tlabel!='': axes.set_ylabel(tlabel)
                axes.set_ylim(matplotlib.dates.date2num(tmin),matplotlib.dates.date2num(tmax))

            # Select tick type and spacing based on the time span to show.
            dayspan = (tmax-tmin).days
            if dayspan/365>10:
              # more than 10 years
              taxis.set_major_locator(matplotlib.dates.YearLocator(base=5))
              taxis.set_major_formatter(matplotlib.dates.DateFormatter('%Y'))
            elif dayspan/365>1:
              # less than 10 but more than 1 year
              taxis.set_major_locator(matplotlib.dates.YearLocator(base=1))
              taxis.set_major_formatter(matplotlib.dates.DateFormatter('%Y'))
            elif dayspan>61:
              # less than 1 year but more than 2 months
              taxis.set_major_locator(matplotlib.dates.MonthLocator(interval=1))
              taxis.set_major_formatter(MonthFormatter())
            elif dayspan>7:
              # less than 2 months but more than 1 day
              taxis.set_major_locator(matplotlib.dates.DayLocator(interval=15))
              taxis.set_major_formatter(matplotlib.dates.DateFormatter('%d %b'))
            elif dayspan>1:
              # less than 1 week but more than 1 day
              taxis.set_major_locator(matplotlib.dates.DayLocator(interval=1))
              taxis.set_major_formatter(matplotlib.dates.DateFormatter('%d %b'))
            else:
              # less than 1 day
              taxis.set_major_locator(matplotlib.dates.HourLocator(interval=1))
              taxis.set_major_formatter(matplotlib.dates.DateFormatter('%H:%M'))

        # Configure depth axis (y-axis), if any.
        if 'z' in dim2axis:
            zaxis = dim2axis['z']

            # Obtain label for depth axis.
            zlabel = self.forcedproperties.getProperty(['DepthAxis','Label'])
            if zlabel==None: zlabel = 'depth (m)'
            self.properties.setProperty(['DepthAxis', 'Label'],zlabel)

            # Configure limits and label of depth axis.
            if zaxis=='x':
                axes.set_xlim(zmin,zmax)
                if zlabel!='': axes.set_xlabel(zlabel)
            elif zaxis=='y':
                axes.set_ylim(zmin,zmax)
                if zlabel!='': axes.set_ylabel(zlabel)
        self.properties.setProperty(['HasDepthAxis'],'z' in dim2axis)

        # Draw the plot to screen.            
        self.canvas.draw()

        # Re-enable property-change notifications; we are done changing plot properties,
        # and want to be notified if anyone else changes them.
        self.ignorechanges = False
        
        self.haschanged = False