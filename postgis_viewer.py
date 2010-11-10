#!/usr/bin/python
"""
Simple PostGIS layer viewer.
Usage: postgis_viewer.py <options>
	
Options:
	-h host
	-p port
	-U user
	-W password
	-d database
	-s schema
	-t table


Using as PgAdmin plugin copy 'postgis_viewer.py' file on PATH and put following to 'plugins.ini':

	Title=View PostGIS layer
	Command=postgis_viewer.py -h $$HOSTNAME -p $$PORT -U $$USERNAME -W $$PASSWORD -d $$DATABASE -s $$SCHEMA -t $$TABLE
	Description=View PostGIS layer
	Platform=unix
	ServerType=postgresql
	Database=Yes
	SetPassword=Yes
"""

import sys
import getopt
#import pdb

from PyQt4.QtSql import *
from PyQt4.QtGui import QAction, QMainWindow, QApplication, QMessageBox
from PyQt4.QtCore import SIGNAL, Qt, QString

from qgis.core import *
from qgis.gui import *

qgis_prefix = "/usr"

class ViewerWnd(QMainWindow):
	def __init__(self, layer):
		QMainWindow.__init__(self)

		self.canvas = QgsMapCanvas()
		self.canvas.setCanvasColor(Qt.white)

		QgsMapLayerRegistry.instance().addMapLayer(layer)

		self.canvas.setExtent(layer.extent())
		self.canvas.setLayerSet( [ QgsMapCanvasLayer(layer) ] )

		self.setCentralWidget(self.canvas)

		actionZoomIn = QAction(QString("Zoom in"), self)
		actionZoomOut = QAction(QString("Zoom out"), self)
		actionPan = QAction(QString("Pan"), self)

		actionZoomIn.setCheckable(True)
		actionZoomOut.setCheckable(True)
		actionPan.setCheckable(True)

		self.connect(actionZoomIn, SIGNAL("triggered()"), self.zoomIn)
		self.connect(actionZoomOut, SIGNAL("triggered()"), self.zoomOut)
		self.connect(actionPan, SIGNAL("triggered()"), self.pan)

		self.toolbar = self.addToolBar("Canvas actions")
		self.toolbar.addAction(actionZoomIn)
		self.toolbar.addAction(actionZoomOut)
		self.toolbar.addAction(actionPan)

		# create the map tools
		self.toolPan = QgsMapToolPan(self.canvas)
		self.toolPan.setAction(actionPan)
		self.toolZoomIn = QgsMapToolZoom(self.canvas, False) # false = in
		self.toolZoomIn.setAction(actionZoomIn)
		self.toolZoomOut = QgsMapToolZoom(self.canvas, True) # true = out
		self.toolZoomOut.setAction(actionZoomOut)

		self.pan()

	def zoomIn(self):
		self.canvas.setMapTool(self.toolZoomIn)

	def zoomOut(self):
		self.canvas.setMapTool(self.toolZoomOut)

	def pan(self):
		self.canvas.setMapTool(self.toolPan)


def show_error(title, text):
	QMessageBox.critical(None, title, text,
	QMessageBox.Ok | QMessageBox.Default,
	QMessageBox.NoButton)
	print 'E: Error. Exiting ...'
	print __doc__
	sys.exit(1)


def main(argv):
	print 'I: Starting viewer ...'
	
	app = QApplication(argv)
	
	db_host = ''
	db_port = '5432'
	db_user = ''
	db_pwd = ''
	db = ''
	db_schema = 'public'
	db_table =  ''


	opts, args = getopt.getopt(sys.argv[1:], 'h:p:U:W:d:s:t:g:', [])
	for o, a in opts:
		if o == '-h':
			db_host = a
		elif o == '-p':
			db_port = a
		elif o == '-U':
			db_user = a
		elif o == '-W':
			db_pwd = a
		elif o == '-d':
			db = a
		elif o == '-s':
			db_schema = a
		elif o == '-t':
			db_table = a

	d = QSqlDatabase.addDatabase("QPSQL", "PgSQLDb")
	d.setHostName(db_host)
	d.setPort(int(db_port))
	d.setDatabaseName(db)
	d.setUserName(db_user)
	d.setPassword(db_pwd)

	if d.open():
		print 'I: Database connection was succesfull'
		
		query = QSqlQuery(d)
		query.exec_("SELECT column_name FROM information_schema.columns \
				WHERE table_schema = '%s' AND \
				table_name = '%s' AND \
				udt_name = 'geometry' LIMIT 1" % (db_schema, db_table))
		
		if query.next():
			geometry_col = query.value(0).toString()
			
			# QGIS libs init
			QgsApplication.setPrefixPath(qgis_prefix, True)
			QgsApplication.initQgis()

			# QGIS connection
			uri = QgsDataSourceURI()
			uri.setConnection(db_host, db_port, db, db_user, db_pwd)
			uri.setDataSource(db_schema, db_table, geometry_col)
			layer = QgsVectorLayer(uri.uri(), db_table, "postgres")

			# Open viewer
			if layer.isValid():
				print 'I: Opening layer %s.%s' % (layer.name(), geometry_col)
				wnd = ViewerWnd(layer)
				wnd.move(100,100)
				wnd.resize(600, 400)
				wnd.show()

				retval = app.exec_()

				# Exit
				QgsApplication.exitQgis()
				print 'I: Exiting ...'
				sys.exit(retval)
		else:
			show_error("Error when opening layer", 
					"Layer doesn't exist or doesn't contain geometry columns.")
	else:
		show_error("Connection error", "Error when connecting to database.")

if __name__ == "__main__":
	main(sys.argv)
