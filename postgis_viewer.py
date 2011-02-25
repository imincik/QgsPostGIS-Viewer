#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Simple PostGIS viewer based on QGIS libs.
Usage: postgis_viewer.py <options>
	
Options:
	-h host
	-p port
	-U user
	-W password
	-d database
	-s schema
	-t table

Prerequisities:
	Qt, QGIS, libqt4-sql-psql

Using as PgAdmin plugin, copy 'postgis_viewer.py' file on PATH and put following 
to 'plugins.ini' (/usr/share/pgadmin3/plugins.ini on Debian):

	Title=View PostGIS layer
	Command=postgis_viewer.py -h $$HOSTNAME -p $$PORT -U $$USERNAME -W $$PASSWORD -d $$DATABASE -s $$SCHEMA -t $$OBJECTNAME
	Description=View PostGIS layer
	Platform=unix
	ServerType=postgresql
	Database=Yes
	SetPassword=Yes

Authors:
	Copyright (c) 2010 by Ivan Mincik, ivan.mincik@gista.sk
	Copyright (c) 2011 German Carrillo, geotux_tuxman@linuxmail.org

License: 
	GNU General Public License v2.0
"""

import os, sys, math
import getopt
import getpass, pickle # import stuff for ipc

try:
	from PyQt4.QtSql import QSqlDatabase, QSqlQuery
	from PyQt4.QtGui import QAction, QMainWindow, QApplication, QMessageBox, QStatusBar, QFrame, QLabel
	from PyQt4.QtCore import SIGNAL, Qt, QString, QSharedMemory, QIODevice
	from PyQt4.QtNetwork import QLocalServer, QLocalSocket

	from qgis.core import QgsApplication, QgsDataSourceURI, QgsVectorLayer, QgsMapLayerRegistry
	from qgis.gui import QgsMapCanvas, QgsMapToolPan, QgsMapToolZoom, QgsMapCanvasLayer

except ImportError:
	print >> sys.stderr, 'E: Qt or QGIS not installed.'
	print >> sys.stderr, 'E: Exiting ...'
	sys.exit(1)

# Set the qgis_prefix according to the current os
qgis_prefix = ""
if os.name == "nt":
	qgis_prefix = "C:/OSGeo4W/apps/qgis/"
else:
	qgis_prefix = "/usr"


class SingletonApp(QApplication):
	
	timeout = 1000
	
	def __init__(self, argv, application_id=None):
		QApplication.__init__(self, argv)
		
		self.socket_filename = unicode(os.path.expanduser("~/.ipc_%s" 
			% self.generate_ipc_id()) )
		self.shared_mem = QSharedMemory()
		self.shared_mem.setKey(self.socket_filename)

		if self.shared_mem.attach():
			self.is_running = True
			return
		
		self.is_running = False
		if not self.shared_mem.create(1):
			print >>sys.stderr, "Unable to create single instance"
			return
		# start local server
		self.server = QLocalServer(self)
		# connect signal for incoming connections
		self.connect(self.server, SIGNAL("newConnection()"), self.receive_message)
		# if socket file exists, delete it
		if os.path.exists(self.socket_filename):
			os.remove(self.socket_filename)
		# listen
		self.server.listen(self.socket_filename)

	def __del__(self):
		self.shared_mem.detach()
		if not self.is_running:
			if os.path.exists(self.socket_filename):
				os.remove(self.socket_filename)

		
	def generate_ipc_id(self, channel=None):
		if channel is None:
			channel = os.path.basename(sys.argv[0])
		return "%s_%s" % (channel, getpass.getuser())

	def send_message(self, message):
		if not self.is_running:
			raise Exception("Client cannot connect to IPC server. Not running.")
		socket = QLocalSocket(self)
		socket.connectToServer(self.socket_filename, QIODevice.WriteOnly)
		if not socket.waitForConnected(self.timeout):
			raise Exception(str(socket.errorString()))
		socket.write(pickle.dumps(message))
		if not socket.waitForBytesWritten(self.timeout):
			raise Exception(str(socket.errorString()))
		socket.disconnectFromServer()
		
	def receive_message(self):
		socket = self.server.nextPendingConnection()
		if not socket.waitForReadyRead(self.timeout):
			print >>sys.stderr, socket.errorString()
			return
		byte_array = socket.readAll()
		self.handle_new_message(pickle.loads(str(byte_array)))

	def handle_new_message(self, message):
		print "Received:", message
		self.emit( SIGNAL("loadPgLayer"), message )


class ViewerWnd( QMainWindow ):
	def __init__( self, app, dictOpts ):
		QMainWindow.__init__( self )

		self.canvas = QgsMapCanvas()
		self.canvas.setCanvasColor( Qt.white )
		self.canvas.enableAntiAliasing( True )
		self.setCentralWidget( self.canvas )

		actionZoomIn = QAction( QString( "Zoom in" ), self )
		actionZoomOut = QAction( QString( "Zoom out" ), self )
		actionPan = QAction( QString( "Pan" ), self )

		actionZoomIn.setCheckable( True )
		actionZoomOut.setCheckable( True )
		actionPan.setCheckable( True )

		self.connect(actionZoomIn, SIGNAL( "triggered()" ), self.zoomIn )
		self.connect(actionZoomOut, SIGNAL( "triggered()" ), self.zoomOut )
		self.connect(actionPan, SIGNAL( "triggered()" ), self.pan )

		self.toolbar = self.addToolBar( "Canvas actions" )
		self.toolbar.addAction( actionZoomIn )
		self.toolbar.addAction( actionZoomOut )
		self.toolbar.addAction( actionPan )

		# create the map tools
		self.toolPan = QgsMapToolPan( self.canvas )
		self.toolPan.setAction( actionPan )
		self.toolZoomIn = QgsMapToolZoom( self.canvas, False ) # false = in
		self.toolZoomIn.setAction( actionZoomIn )
		self.toolZoomOut = QgsMapToolZoom( self.canvas, True ) # true = out
		self.toolZoomOut.setAction( actionZoomOut )
		
		# Create the toolbar
		self.statusbar = QStatusBar( self )
		self.statusbar.setObjectName( "statusbar" )
		self.setStatusBar( self.statusbar )

		self.lblXY = QLabel()
		self.lblXY.setFrameStyle( QFrame.Box )
		self.lblXY.setMinimumWidth( 170 )
		self.lblXY.setAlignment( Qt.AlignCenter )
		self.statusbar.setSizeGripEnabled( False )
		self.statusbar.addPermanentWidget( self.lblXY, 0 )

		self.lblScale = QLabel()
		self.lblScale.setFrameStyle( QFrame.StyledPanel )
		self.lblScale.setMinimumWidth( 140 )
		self.statusbar.addPermanentWidget( self.lblScale, 0 )

		self.connect( app, SIGNAL( "loadPgLayer" ), self.loadLayer )
		self.connect( self.canvas, SIGNAL( "scaleChanged(double)" ),
			self.changeScale )
		self.connect( self.canvas, SIGNAL( "xyCoordinates(const QgsPoint&)" ),
			self.updateXY )

		self.pan()

		self.layers = [] 
		self.loadLayer( dictOpts )
	
	def zoomIn( self ):
		self.canvas.setMapTool( self.toolZoomIn )

	def zoomOut( self ):
		self.canvas.setMapTool( self.toolZoomOut )

	def pan( self ):
		self.canvas.setMapTool( self.toolPan )

	def loadLayer( self, dictOpts ):

		if not self.isActiveWindow():
			self.activateWindow()
			self.raise_() 

		# QGIS connection
		uri = QgsDataSourceURI()
		uri.setConnection( dictOpts['-h'], dictOpts['-p'], dictOpts['-d'], dictOpts['-U'], dictOpts['-W'] )
		uri.setDataSource( dictOpts['-s'], dictOpts['-t'], dictOpts['-g'] )
		layer = QgsVectorLayer( uri.uri(), dictOpts['-t'], "postgres" )

		if layer.isValid():
			QgsMapLayerRegistry.instance().addMapLayer( layer )
			if self.canvas.layerCount() == 0:
				self.canvas.setExtent( layer.extent() )

			self.layers.insert( 0, QgsMapCanvasLayer( layer ) )
			self.canvas.setLayerSet( self.layers )

	def changeScale( self, scale ):
		self.lblScale.setText( "Scale 1:" + formatNumber( scale ) )

	def updateXY( self, p ):
		if self.canvas.mapUnits() == 2: # Degrees
			self.lblXY.setText( formatToDegrees( p.x() ) + " | " \
				+ formatToDegrees( p.y() ) )
		else: # XY
			self.lblXY.setText( self.formatNumber( p.x() ) + " | " \
				+ self.formatNumber( p.y() ) + "" )


def formatNumber( number, precision=0, group_sep='.', decimal_sep=',' ):
	"""
		number: Nomber to be formatted 
		precision: Number of decimals
		group_sep: Miles separator
		decimal_sep: Decimal separator
	"""
	number = ( '%.*f' % ( max( 0, precision ), number ) ).split( '.' )
	integer_part = number[ 0 ]

	if integer_part[ 0 ] == '-':
		sign = integer_part[ 0 ]
		integer_part = integer_part[ 1: ]
	else:
		sign = ''

	if len( number ) == 2:
		decimal_part = decimal_sep + number[ 1 ]
	else:
		decimal_part = ''

	integer_part = list( integer_part )
	c = len( integer_part )

	while c > 3:
		c -= 3
		integer_part.insert( c, group_sep )

	return sign + ''.join( integer_part ) + decimal_part

def formatToDegrees( number ):
	""" Returns the degrees-minutes-seconds form of number """
	sign = ''
	if number < 0:
		number = math.fabs( number )
		sign = '-'

	deg = math.floor( number )
	minu = math.floor( ( number - deg ) * 60 )
	sec = ( ( ( number - deg ) * 60 ) - minu ) * 60 

	return sign + "%.0f"%deg + 'º ' + "%.0f"%minu + "' " \
		+ "%.2f"%sec + "\""

def show_error(title, text):
	QMessageBox.critical(None, title, text,
	QMessageBox.Ok | QMessageBox.Default,
	QMessageBox.NoButton)
	print >> sys.stderr, 'E: Error. Exiting ...'
	print __doc__
	sys.exit(1)


def main( argv ):
	print 'I: Starting viewer ...'
	app = SingletonApp( argv )

	dictOpts = { '-h':'', '-p':'5432', '-U':'', '-W':'', '-d':'', '-s':'public', '-t':'', '-g':'' }

	opts, args = getopt.getopt( sys.argv[1:], 'h:p:U:W:d:s:t:g:', [] )
	dictOpts.update( opts )
	
	if dictOpts['-t'] == '':
		print >> sys.stderr, 'E: Table name is required'
		print __doc__
		sys.exit( 1 )

	d = QSqlDatabase.addDatabase( "QPSQL", "PgSQLDb" )
	d.setHostName( dictOpts['-h'] )
	d.setPort( int( dictOpts['-p'] ) )
	d.setDatabaseName( dictOpts['-d'] )
	d.setUserName( dictOpts['-U'] )
	d.setPassword( dictOpts['-W'] )

	if d.open():
		print 'I: Database connection was succesfull'
		
		query = QSqlQuery( d )
		query.exec_( "SELECT column_name FROM information_schema.columns \
				WHERE table_schema = '%s' AND \
				table_name = '%s' AND \
				udt_name = 'geometry' LIMIT 1" % ( dictOpts['-s'], dictOpts['-t'] ) )

		if query.next():
			dictOpts[ '-g' ] = str( query.value( 0 ).toString() )

			if app.is_running:
				# Application already running, send message to load data
				app.send_message( dictOpts )
			else:
				# Start the Viewer

				# QGIS libs init
				QgsApplication.setPrefixPath(qgis_prefix, True)
				QgsApplication.initQgis()

				# Open viewer
				wnd = ViewerWnd( app, dictOpts )
				wnd.move(100,100)
				wnd.resize(400, 300)
				wnd.show()

				retval = app.exec_()

				# Exit
				QgsApplication.exitQgis()
				print 'I: Exiting ...'
				sys.exit(retval)
		else:
			show_error("Error when opening layer", 
					"Layer '%s.%s' doesn't exist or it doesn't contain geometry column." % (dictOpts['-s'], dictOpts['-t']))
	else:
		show_error("Connection error", "Error when connecting to database.")

if __name__ == "__main__":
	main( sys.argv )
