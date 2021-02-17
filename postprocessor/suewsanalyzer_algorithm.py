# -*- coding: utf-8 -*-


__author__ = 'Fredrik Lindberg'
__date__ = '2021-02-05'
__copyright__ = '(C) 2021 by Fredrik Lindberg'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterDestination,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterEnum,
                       QgsProcessingException,
                       QgsFeature,
                       QgsVectorFileWriter,
                       QgsVectorDataProvider,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterDefinition)
from qgis.PyQt.QtGui import QIcon
from osgeo import gdal, osr, ogr
from osgeo.gdalconst import *
import os
import numpy as np
import inspect
from pathlib import Path
import sys

def saverasternd(gdal_data, filename, raster):
    rows = gdal_data.RasterYSize
    cols = gdal_data.RasterXSize

    outDs = gdal.GetDriverByName("GTiff").Create(filename, cols, rows, int(1), GDT_Float32)
    outBand = outDs.GetRasterBand(1)

    # write the data
    outBand.WriteArray(raster, 0, 0)
    # flush data to disk, set the NoData value and calculate stats
    outBand.FlushCache()
    # outBand.SetNoDataValue(-9999)

    # georeference the image and set the projection
    outDs.SetGeoTransform(gdal_data.GetGeoTransform())
    outDs.SetProjection(gdal_data.GetProjection())

class ProcessingSuewsAnalyzerAlgorithm(QgsProcessingAlgorithm):
    """
    This class is a processing version of SuewsAnalyzer but only for generating aggregated grids
    """
    SUEWS_NL = 'SUEWS_NL'
    VARIA_IN = 'VARIA_IN'
    INPUT_POLYGONLAYER = 'INPUT_POLYGONLAYER'
    ID_FIELD = 'ID_FIELD'
    YEAR = 'YEAR'
    DAY_START = 'DAY_START'
    DAY_END = 'DAY_END'
    IRREGULAR = 'IRREGULAR'
    PIXELSIZE = 'PIXELSIZE'
    STAT_TYPE = 'STAT_TYPE'

    # Output
    SUEWS_GRID_ = 'SUEWS_GRID_OUT'


    def initAlgorithm(self, config):
        self.varType = ((self.tr('Mean Radiant Temperature (Tmrt)'), '0'),
                        (self.tr('Incoming Longwave radiation (Ldown)'), '1'),
                        (self.tr('Outgoing Longwave radiation (Lup)'), '2'),
                        (self.tr('Incoming Shortwave radiation (Kdown)'), '3'),
                        (self.tr('Outgoing Shortwave radiation (Kup)'), '4'),
                        (self.tr('Ground Shadow'), '5'))
        self.addParameter(QgsProcessingParameterFile(self.SUEWS_NL,
                                                     self.tr('SUEWS RunControl namelist'),
                                                     extension='nml',
                                                     optional=False))

        self.addParameter(QgsProcessingParameterEnum(self.VARIA_IN,
                                                     self.tr('Variable to post-process (must be availabe in the SOLWEIG output folder)'),
                                                     options=[i[0] for i in self.varType],
                                                     defaultValue=False))
        # self.addParameter(QgsProcessingParameterFile(self.SOLWEIG_DIR,
        #                                              self.tr('Path to SOLWEIG output folder'),
        #                                              QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterRasterLayer(self.BUILDINGS,
                                                            self.tr('Raster to exclude building pixels from analysis'),
                                                             '', 
                                                             optional=True))

        self.statType = ((self.tr('Diurnal Average'), '0'),
                         (self.tr('Daytime average'), '1'),
                         (self.tr('Nighttime average'), '2'),
                         (self.tr('Maximum'), '3'),
                         (self.tr('Minimun'), '4'))
        self.addParameter(QgsProcessingParameterEnum(self.STAT_TYPE,
                                                     self.tr('Statistic measure'),
                                                     options=[i[0] for i in self.statType],
                                                     defaultValue=1))


        self.addParameter(QgsProcessingParameterNumber(self.TMRT_THRES_NUM,
                                                       self.tr('Theshold (degC)'),
                                                       QgsProcessingParameterNumber.Double,
                                                       QVariant(55), 
                                                       False))

        # Output
        self.addParameter(QgsProcessingParameterRasterDestination(self.STAT_OUT,
                                                                  self.tr("Output raster from statistical analysis"),
                                                                  None,
                                                                  optional=False))
        self.addParameter(QgsProcessingParameterRasterDestination(self.TMRT_STAT_OUT,
                                                                  self.tr("Output raster from Tmrt theshold analysis"),
                                                                  None,
                                                                  optional=True))

    def processAlgorithm(self, parameters, context, feedback):
        
        # InputParameters
        solweigDir = self.parameterAsString(parameters, self.SOLWEIG_DIR, context)
        variaIn = self.parameterAsString(parameters, self.VARIA_IN, context)
        buildings = self.parameterAsRasterLayer(parameters, self.BUILDINGS, context) 
        statTypeStr = self.parameterAsString(parameters, self.STAT_TYPE, context)
        thresTypeStr = self.parameterAsString(parameters, self.THRES_TYPE, context)
        thresNum = self.parameterAsDouble(parameters, self.TMRT_THRES_NUM, context)
        outputStat = self.parameterAsOutputLayer(parameters, self.STAT_OUT, context)
        outputTMRT = None

        feedback.setProgressText("Initializing...")

        statType = int(statTypeStr)
        thresType = int(thresTypeStr)

        self.posAll = []
        self.posDay = []
        self.posNight = []
        # self.posSpecMean = []
        # self.posSpecMax = []
        # self.posSpecMin = []

        # SOLWEIGANALYZER CODE
        self.l = os.listdir(solweigDir)
        
        if variaIn == '0':
            self.var = 'Tmrt'
        elif variaIn == '1':
            self.var = 'Ldown'
        elif variaIn == '2':
            self.var = 'Lup'
        elif variaIn == '3':
            self.var = 'Kdown'
        elif variaIn == '4':
            self.var = 'Kup'
        elif variaIn == '5':
            self.var = 'Shadow'

        if not self.var in str(self.l):
            raise QgsProcessingException('Filename starting with "' + self.var + '" is not found in SOLWEIG output folder.')

        index = 0
        for file in self.l:
            if file.startswith(self.var + '_'):
                if not file.endswith('_average.tif'):
                    if not file.endswith('.xml'): # response to issue #196
                        self.posAll.append(index)
                if file.endswith('D.tif'):
                    self.posDay.append(index)
                if file.endswith('N.tif'):
                    self.posNight.append(index)
                # if file[-9:-5] == self.dlg.comboBoxSpecificMean.currentText():
                #     self.posSpecMean.append(index)
                # if file[-9:-5] == self.dlg.comboBoxSpecificMax.currentText():
                #     self.posSpecMax.append(index)
                # if file[-9:-5] == self.dlg.comboBoxSpecificMin.currentText():
                #     self.posSpecMin.append(index)
            index += 1

        # Exclude buildings
        if buildings is None:
                feedback.setProgressText("No building raster loaded.")
        else:
            provider = buildings.dataProvider()
            filepath_dsm = str(provider.dataSourceUri())
            self.gdal_dsm = gdal.Open(filepath_dsm)
            self.build = self.gdal_dsm.ReadAsArray().astype(np.float)
            geotransform = self.gdal_dsm.GetGeoTransform()
            self.scale = 1 / geotransform[1]
        
        # Diurnal mean
        if statType == 0:
            feedback.setProgressText('Calculating ' + self.var + ' diurnal mean.')
            index = 0
            for i in self.posAll:
                gdal_dsm = gdal.Open(solweigDir + '/' + self.l[i])
                grid = gdal_dsm.ReadAsArray().astype(np.float)
                if index == 0:
                    sizex = grid.shape[0]
                    sizey = grid.shape[1]
                    gridall = np.zeros((sizex, sizey))
                gridall += grid
                index += 1

            gridall = gridall / index

            if buildings is not None:
                gridall[self.build == 0] = -9999

            saverasternd(gdal_dsm, outputStat, gridall)

        # Daytime mean
        if statType == 1:
            feedback.setProgressText('Calculating ' + self.var + ' daytime mean.')
            index = 0
            for i in self.posDay:
                gdal_dsm = gdal.Open(solweigDir + '/' + self.l[i])
                grid = gdal_dsm.ReadAsArray().astype(np.float)
                if index == 0:
                    sizex = grid.shape[0]
                    sizey = grid.shape[1]
                    daymean = np.zeros((sizex, sizey))
                daymean += grid
                index += 1

            daymean = daymean / index

            if buildings is not None:
                daymean[self.build == 0] = -9999

            saverasternd(gdal_dsm, outputStat, daymean)

        # Nighttime mean
        if statType == 2:
            feedback.setProgressText('Calculating ' + self.var + ' nighttime mean.')
            index = 0
            for i in self.posNight:
                gdal_dsm = gdal.Open(solweigDir + '/' + self.l[i])
                grid = gdal_dsm.ReadAsArray().astype(np.float)
                if index == 0:
                    sizex = grid.shape[0]
                    sizey = grid.shape[1]
                    daymean = np.zeros((sizex, sizey))
                daymean += grid
                index += 1

            daymean = daymean / index

            if buildings is not None:
                daymean[self.build == 0] = -9999

            saverasternd(gdal_dsm, outputStat, daymean)

        # Max
        if statType == 3:
            feedback.setProgressText('Calculating ' + self.var + ' max.')
            index = 0
            for i in self.posAll:
                gdal_dsm = gdal.Open(solweigDir + '/' + self.l[i])
                grid = gdal_dsm.ReadAsArray().astype(np.float)
                if index == 0:
                    sizex = grid.shape[0]
                    sizey = grid.shape[1]
                    gridall = np.zeros((sizex, sizey)) - 100.
                gridall = np.maximum(gridall, grid)
                index += 1

            if buildings is not None:
                gridall[self.build == 0] = -9999

            saverasternd(gdal_dsm, outputStat, gridall)

        # Min
        if statType == 4:
            feedback.setProgressText('Calculating ' + self.var + ' min.')
            index = 0
            for i in self.posAll:
                gdal_dsm = gdal.Open(solweigDir + '/' + self.l[i])
                grid = gdal_dsm.ReadAsArray().astype(np.float)
                if index == 0:
                    sizex = grid.shape[0]
                    sizey = grid.shape[1]
                    gridall = np.zeros((sizex, sizey)) + 100.
                gridall = np.minimum(gridall, grid)
                index += 1

            if buildings is not None:
                gridall[self.build == 0] = -9999

            saverasternd(gdal_dsm, outputStat, gridall)


        # Tmrt threshold above
        if thresType == 1:
            feedback.setProgressText('Calculating Tmrt percent time above ' + str(thresNum) + ' degC.')
            outputTMRT = self.parameterAsOutputLayer(parameters, self.TMRT_STAT_OUT, context)
            index = 0
            for i in self.posAll:
                gdal_dsm = gdal.Open(solweigDir + '/' + self.l[i])
                grid = gdal_dsm.ReadAsArray().astype(np.float)
                if index == 0:
                    sizex = grid.shape[0]
                    sizey = grid.shape[1]
                    daymean = np.zeros((sizex, sizey))

                tempgrid = (grid > thresNum)
                daymean = daymean + tempgrid
                index += 1

            daymean = daymean / index

            if buildings is not None:
                daymean[self.build == 0] = -9999

            saverasternd(gdal_dsm, outputTMRT, daymean) # response to issue #218

        # Tmrt threshold below
        if thresType == 2:
            feedback.setProgressText('Calculating Tmrt percent time below ' + str(thresNum) + ' degC.')
            outputTMRT = self.parameterAsOutputLayer(parameters, self.TMRT_STAT_OUT, context)
            index = 0
            for i in self.posAll:
                gdal_dsm = gdal.Open(solweigDir + '/' + self.l[i])
                grid = gdal_dsm.ReadAsArray().astype(np.float)
                if index == 0:
                    sizex = grid.shape[0]
                    sizey = grid.shape[1]
                    daymean = np.zeros((sizex, sizey))
                tempgrid = (grid < thresNum)
                daymean = daymean + tempgrid
                index += 1

            daymean = daymean / index

            if buildings is not None:
                daymean[self.build == 0] = -9999

            saverasternd(gdal_dsm, outputTMRT, daymean)  # response to issue #218

        del self.posAll[:]


        feedback.setProgressText("Processing finished.")

        return {self.STAT_OUT: outputTMRT, self.TMRT_STAT_OUT: outputTMRT}
    
    def name(self):
        return 'Urban Energy Balance: SUEWS Analyzer'

    def displayName(self):
        return self.tr(self.name())

    def group(self):
        return self.tr(self.groupId())

    def groupId(self):
        return 'Post-Processor'

    def shortHelpString(self):
        return self.tr('The <b>SUEWS Analyzer</b> plugin can be used to make basic grid analysis of model results generated by the SUEWS model.<br>'
        '\n'
        '--------------\n'
        'Full manual available via the <b>Help</b>-button.')

    def helpUrl(self):
        url = "https://umep-docs.readthedocs.io/en/latest/post_processor/Urban%20Energy%20Balance%20SUEWS%20Analyser.html"
        return url

    def tr(self, string):
        return QCoreApplication.translate('Post-Processing', string)

    def icon(self):
        cmd_folder = Path(os.path.split(inspect.getfile(inspect.currentframe()))[0]).parent
        icon = QIcon(str(cmd_folder) + "/icons/SuewsLogo.png")
        return icon

    def createInstance(self):
        return ProcessingSuewsAnalyzerAlgorithm()
