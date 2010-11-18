#!/usr/bin/python
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

Author: Ivan Mincik, ivan.mincik@gista.sk
License: GNU General Public License v2.0
"""

import sys
import getopt
#import pdb

try:
	from PyQt4.QtSql import *
	from PyQt4.QtGui import QAction, QMainWindow, QApplication, QMessageBox, QDockWidget, QListWidget
	from PyQt4.QtCore import SIGNAL, Qt, QString, QStringList, QVariant

	from qgis.core import *
	from qgis.gui import *

except ImportError:
	print >> sys.stderr, 'E: Qt or QGIS not installed.'
	print >> sys.stderr, 'E: Exiting ...'
	sys.exit(1)


qgis_prefix = "/usr"

class ViewerWnd(QMainWindow):
	def __init__(self, layer, prop):
		QMainWindow.__init__(self)

		self.setWindowTitle('PostGIS Viewer - %s' % (layer.name()))

		self.canvas = QgsMapCanvas()
		self.canvas.setCanvasColor(Qt.white)
		self.canvas.enableAntiAliasing(True)

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

		dock = QDockWidget(self.tr('Layer Properties'), self)
		dock.setAllowedAreas(Qt.BottomDockWidgetArea)
		self.customerList = QListWidget(dock)
		self.customerList.addItems(QStringList()
			<< "Layer: %s" % layer.name()
			<< "Source: %s" % layer.source()
			<< "Geometry: %s" % prop['geom_type']
			<< "Extent: %s" % layer.extent().toString()
			<< "PostGIS: %s" % prop['postgis_version']
			)
		dock.setWidget(self.customerList)
		self.addDockWidget(Qt.BottomDockWidgetArea, dock)

	def zoomIn(self):
		self.canvas.setMapTool(self.toolZoomIn)

	def zoomOut(self):
		self.canvas.setMapTool(self.toolZoomOut)

	def pan(self):
		self.canvas.setMapTool(self.toolPan)


class PgisLayer:
	def __init__(self, db_host, db_port, db, db_user, db_pwd, db_schema, db_table):
		self.db = QSqlDatabase.addDatabase("QPSQL", "PgisLayer")
		self.db.setHostName(db_host)
		self.db.setPort(int(db_port))
		self.db.setDatabaseName(db)
		self.db.setUserName(db_user)
		self.db.setPassword(db_pwd)
		
		self.db_schema = db_schema
		self.db_table = db_table

		self.db.open()

	def _exec_sql(self, sql):
		cur = QSqlQuery(self.db)
		cur.exec_(sql)
		return cur

	def connection_success(self):
		if self.db.open():
			return True
		else:
			return False
	
	def postgis_version(self):
		que = self._exec_sql('SELECT postgis_full_version()')
		que.next()
		return que.value(0)
	
	def get_geom_column(self):
		que = self._exec_sql("SELECT column_name FROM information_schema.columns \
			WHERE table_schema = '%s' AND \
			table_name = '%s' AND \
			udt_name = 'geometry' LIMIT 1" % (self.db_schema, self.db_table))
		
		if que.next():
			return que.value(0)
	
	def get_geom_type(self):
		que = self._exec_sql("SELECT type FROM geometry_columns \
			WHERE f_table_schema = '%s' AND \
			f_table_name = '%s'" % (self.db_schema, self.db_table))
		
		if que.next():
			return que.value(0)
		else:
			que = self._exec_sql("SELECT GeometryType(the_geom) FROM %s.%s LIMIT 1" % (self.db_schema, self.db_table))
			if que.next():
				return que.value(0)
			else:
				return QVariant('undefined')



def show_error(title, text):
	QMessageBox.critical(None, title, text,
	QMessageBox.Ok | QMessageBox.Default,
	QMessageBox.NoButton)
	print >> sys.stderr, 'E: Error. Exiting ...'
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
	
	if db_table == '':
		print >> sys.stderr, 'E: Table name is required'
		print __doc__
		sys.exit(1)

	lay = PgisLayer(db_host, db_port, db, db_user, db_pwd, db_schema, db_table)
	
	if lay.connection_success():
		geometry_col = lay.get_geom_column().toString()
		
		if geometry_col:
			# QGIS libs init
			QgsApplication.setPrefixPath(qgis_prefix, True)
			QgsApplication.initQgis()

			# QGIS connection
			uri = QgsDataSourceURI()
			uri.setConnection(db_host, db_port, db, db_user, db_pwd)
			uri.setDataSource(db_schema, db_table, geometry_col)
			layer = QgsVectorLayer(uri.uri(), db_table, 'postgres')

			# Open viewer
			if layer.isValid():
				# collect some layer properties
				layer_prop = {}
				layer_prop['postgis_version'] = lay.postgis_version().toString()
				layer_prop['geom_type'] = lay.get_geom_type().toString()

				print 'I: Opening layer %s.%s' % (layer.name(), geometry_col)
				wnd = ViewerWnd(layer, layer_prop)
				wnd.move(100, 100)
				wnd.resize(600, 400)
				wnd.show()

				retval = app.exec_()

				# Exit
				QgsApplication.exitQgis()
				print 'I: Exiting ...'
				sys.exit(retval)

		else:
			show_error("Error when opening layer", 
					"Layer '%s.%s' doesn't exist or it doesn't contain geometry column." % (db_schema, db_table))
	else:
		show_error("Connection error", "Error when connecting to database.")

if __name__ == "__main__":
	main(sys.argv)
