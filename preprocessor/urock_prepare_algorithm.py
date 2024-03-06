# -*- coding: utf-8 -*-

"""
/***************************************************************************
 URockPrepare
                                 A QGIS plugin
 This plugin generates URock spatial inputs: building and vegetation vector layers with height attribute 
using rasters (DEM, DSM, CDSM) and building footprint
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2022-07-15
        copyright            : (C) 2022 by Jérémy Bernard / University of Gothenburg
        email                : jeremy.bernard@zaclys.net
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = 'Jérémy Bernard / University of Gothenburg'
__date__ = '2022-07-15'
__copyright__ = '(C) 2022 by Jérémy Bernard / University of Gothenburg'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

import os
import re
import tempfile
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterString,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterVectorDestination,
                       QgsProcessingParameterBoolean,
                       QgsVectorLayer,
                       QgsCoordinateReferenceSystem,
                       QgsProperty,
                       QgsProcessingContext,
                       QgsProject,
                       QgsProcessingException)
import processing
from qgis.PyQt.QtGui import QIcon
import inspect
from pathlib import Path
from ..functions.URock.GlobalVariables import *

class URockPrepareAlgorithm(QgsProcessingAlgorithm):
    """
    This is an example algorithm that takes a vector layer and
    creates a new identical one.

    It is meant to be used as an example of how to create your own
    algorithms and explain methods and variables used to do it. An
    algorithm like this will be available in all elements, and there
    is not need for additional work.

    All Processing algorithms should extend the QgsProcessingAlgorithm
    class.
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    # Input variables
    INPUT_BUILD_FOOTPRINT = 'INPUT_BUILD_FOOTPRINT'
    INPUT_BUILD_DEM = "INPUT_BUILD_DEM"
    INPUT_BUILD_DSM = "INPUT_BUILD_DSM"
    INPUT_VEG_CDSM = "INPUT_VEG_CDSM"
    INPUT_VEG_POINTS = "INPUT_VEG_POINTS"
    
    # OTHER PARAMETERS
    HEIGHT_VEG_FIELD = "HEIGHT_VEG_FIELD"
    RADIUS_VEG_FIELD = "RADIUS_VEG_FIELD"
    VEGETATION_ASPECT = "VEGETATION_ASPECT"
    OUTPUT_BUILD_HEIGHT_FIELD = "OUTPUT_BUILD_HEIGHT_FIELD"
    OUTPUT_VEG_HEIGHT_FIELD = "OUTPUT_VEG_HEIGHT_FIELD"

    # Output variables    
    OUTPUT_BUILDING_FILE = "BUILDINGS_WITH_HEIGHT"
    OUTPUT_VEGETATION_FILE = "VEGETATION_WITH_HEIGHT"
    
    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # We add the input parameters
        # First the layers used as input and output
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_BUILD_FOOTPRINT,
                self.tr('Buildings footprint'),
                [QgsProcessing.TypeVectorPolygon],
                optional = True))
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_BUILD_DSM,
                self.tr('Buildings raster DSM (3D objects + ground or only 3D objects) [m asl or m agl]'), 
                None,
                optional = True))
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_BUILD_DEM,
                self.tr('DEM (ground - only if building DSM is 3D objects + ground) [m asl]'), 
                None,
                optional = True))
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_VEG_CDSM,
                self.tr('Vegetation raster DSM (3D canopy) [m agl]'), 
                None,
                optional = True))
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_VEG_POINTS,
                self.tr('Vegetation point data (trunk location and max height)'),
                [QgsProcessing.TypeVectorPoint],
                optional = True))
        
        
        # Some input parameters
        self.addParameter(
            QgsProcessingParameterField(
                self.HEIGHT_VEG_FIELD,
                self.tr('Vegetation height field'),
                None,
                self.INPUT_VEG_POINTS,
                QgsProcessingParameterField.Numeric,
                optional = True))
        self.addParameter(
            QgsProcessingParameterField(
                self.RADIUS_VEG_FIELD,
                self.tr('Horizontal vegetation radius field'),
                None,
                self.INPUT_VEG_POINTS,
                QgsProcessingParameterField.Numeric,
                optional = True))
        self.addParameter(
            QgsProcessingParameterString(
                self.VEGETATION_ASPECT,
                self.tr('Tree height / tree crown radius ratio used if either height or radius value is missing'),
                defaultValue = 0.75,
                optional = True))

        # We add several output parameters
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_BUILDING_FILE,
                self.tr('Output building vector file'),
                defaultValue = os.path.join(TEMPO_DIRECTORY, f"build_vector{OUTPUT_VECTOR_EXTENSION}")))
        self.addParameter(
            QgsProcessingParameterString(
                self.OUTPUT_BUILD_HEIGHT_FIELD,
                self.tr('Attribute name for building height in output table'),
                defaultValue = 'ROOF_HEIGHT',
                optional = True))
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_VEGETATION_FILE,
                self.tr('Output vegetation vector file'),
                defaultValue = os.path.join(TEMPO_DIRECTORY, f"veg_vector{OUTPUT_VECTOR_EXTENSION}")))
        self.addParameter(
            QgsProcessingParameterString(
                self.OUTPUT_VEG_HEIGHT_FIELD,
                self.tr('Attribute name for vegetation height in output table'),
                defaultValue = 'VEG_HEIGHT',
                optional = True))  
        

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        # Get the tmp directory to save some intermediate results with a known file name
        tmp_dir = tempfile.gettempdir()
        
        # Get building and vegetation layers
        inputBuildinglayer = self.parameterAsVectorLayer(parameters, self.INPUT_BUILD_FOOTPRINT, context)
        inputVeglayer = self.parameterAsVectorLayer(parameters, self.INPUT_VEG_POINTS, context)

        # Get vegetation height attribute
        heightVegField = self.parameterAsString(parameters, self.HEIGHT_VEG_FIELD, context)
        radiusVegField = self.parameterAsString(parameters, self.RADIUS_VEG_FIELD, context)
        
        # Get some other parameters related to vegetation
        vegetationAspect = self.parameterAsDouble(parameters, self.VEGETATION_ASPECT, context)
        
        # Get building raster layers
        build_dsm = self.parameterAsRasterLayer(parameters, self.INPUT_BUILD_DSM, context)
        build_dem = self.parameterAsRasterLayer(parameters, self.INPUT_BUILD_DEM, context)
        veg_dsm = self.parameterAsRasterLayer(parameters, self.INPUT_VEG_CDSM, context)
        
        # Get output file paths
        outputBuildFilepath = self.parameterAsOutputLayer(parameters, self.OUTPUT_BUILDING_FILE, context)
        buildingHeightField = self.parameterAsString(parameters, self.OUTPUT_BUILD_HEIGHT_FIELD, context)
        outputVegFilepath = self.parameterAsOutputLayer(parameters, self.OUTPUT_VEGETATION_FILE, context)
        vegetHeightField = self.parameterAsString(parameters, self.OUTPUT_VEG_HEIGHT_FIELD, context)
        
        #  If output not set, create temporary files for building and vegetation
        veg_out_basepath = outputVegFilepath.split(".")[0]
        veg_out_ext = outputVegFilepath.split(".")[-1].lower()
        build_out_basepath = outputBuildFilepath.split(".")[0]
        build_out_ext = outputBuildFilepath.split(".")[-1].lower()
        if veg_out_ext == 'file':
            outputVegFilepath = os.path.join(tmp_dir, f"veg_vector{OUTPUT_VECTOR_EXTENSION}")
        elif (veg_out_ext != "geojson") and (veg_out_ext != ".shp"):
             outputVegFilepath = veg_out_basepath + OUTPUT_VECTOR_EXTENSION
             feedback.pushWarning(f'.gpkg format is currently not available, output vegetation file extension has been changed to {OUTPUT_VECTOR_EXTENSION}')
        if build_out_ext == 'file':
            outputBuildFilepath = os.path.join(tmp_dir, f"build_vector{OUTPUT_VECTOR_EXTENSION}")
        elif (build_out_ext != "geojson") and (build_out_ext != ".shp"):
             outputBuildFilepath = build_out_basepath + OUTPUT_VECTOR_EXTENSION
             feedback.pushWarning(f'.gpkg format is currently not available, output building file extension has been changed to {OUTPUT_VECTOR_EXTENSION}')

        # BUILDING LAYER CREATION
        # Create the building vector layer if at least building footprint and building dsm have been provided
        if inputBuildinglayer and build_dsm:
            # Reproject the building DSM to the building vector projection if needed
            srid_vbuild = inputBuildinglayer.crs().postgisSrid()
            srid_dsm_build = build_dsm.crs().postgisSrid()
            if srid_vbuild != srid_dsm_build:
               build_dsm = processing.run("gdal:warpreproject", 
                                          {'INPUT': build_dsm,
                                           'SOURCE_CRS':QgsCoordinateReferenceSystem('EPSG:{0}'.format(srid_dsm_build)),
                                           'TARGET_CRS':QgsCoordinateReferenceSystem('EPSG:{0}'.format(srid_vbuild)),
                                           'RESAMPLING':0,'NODATA':None,'TARGET_RESOLUTION':None,
                                           'OPTIONS':'','DATA_TYPE':0,'TARGET_EXTENT':None,
                                           'TARGET_EXTENT_CRS':None,'MULTITHREADING':False,
                                           'EXTRA':'','OUTPUT':os.path.join(tmp_dir,
                                                                            "build_dsm")})["OUTPUT"]
               # Set file name since they are used in raster calculator formula later
               build_dsm_fieldname = "build_dsm"
            else:
               # Get file name since they are used in raster calculator formula later
               build_dsm_filename = str(build_dsm.dataProvider().dataSourceUri()).split(os.sep)[-1].split(".")[0]
               build_dsm_fieldname = re.sub('[-0123456789]', '', build_dsm_filename)[0:11]

            # Create DSM above ground if a DEM is provided
            if build_dem:
                # Reproject the building DEM to the building vector projection if needed
                srid_dem_build = build_dem.crs().postgisSrid()
                if srid_vbuild != srid_dem_build:
                   build_dem = processing.run("gdal:warpreproject", 
                                              {'INPUT': build_dem,
                                               'SOURCE_CRS':QgsCoordinateReferenceSystem('EPSG:{0}'.format(srid_dem_build)),
                                               'TARGET_CRS':QgsCoordinateReferenceSystem('EPSG:{0}'.format(srid_vbuild)),
                                               'RESAMPLING':0,'NODATA':None,'TARGET_RESOLUTION':None,
                                               'OPTIONS':'','DATA_TYPE':0,'TARGET_EXTENT':None,
                                               'TARGET_EXTENT_CRS':None,'MULTITHREADING':False,
                                               'EXTRA':'','OUTPUT':os.path.join(tmp_dir,
                                                                                "build_dem")})["OUTPUT"]
                   # Set file name since they are used in raster calculator formula later
                   build_dem_fieldname = "build_dem"                   

                else:
                    # Get file name since they are used in raster calculator formula later
                    build_dem_filename = str(build_dem.dataProvider().dataSourceUri()).split(os.sep)[-1].split(".")[0]
                    build_dem_fieldname = re.sub('[-0123456789]', '', build_dem_filename)[0:11]
                
                # Calculate the difference between DSM and DEM (set negative values to 0)
                diff_expression = '(\"{0}@1\">\"{1}@1\") * (\"{0}@1\"-\"{1}@1\") + (\"{0}@1\" <= \"{1}@1\") * 0'.format(build_dsm_fieldname,
                                                                                                                        build_dem_fieldname)
                
                build_dsm = processing.run("gdal:rastercalculator", 
                                           {'INPUT_A':build_dsm,
                                            'BAND_A':1,
                                            'INPUT_B':build_dem,
                                            'BAND_B':1,
                                            'INPUT_C':None,
                                            'BAND_C':None,
                                            'INPUT_D':None,
                                            'BAND_D':None,
                                            'INPUT_E':None,
                                            'BAND_E':None,
                                            'INPUT_F':None,
                                            'BAND_F':None,
                                            'FORMULA':'(A > B) * (A - B) + (A <= B) * 0',
                                            'NO_DATA':None,
                                            'RTYPE':5,
                                            'OPTIONS':'',
                                            'EXTRA':'','OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
            
            # Make valid all vector geometries
            tempoBuildinglayer = processing.run("native:fixgeometries", 
                                                {'INPUT':inputBuildinglayer,
                                                 'OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
            
            # Calculate the median height of the DSM within each building footprint
            tempoBuildinglayer2 = processing.run("native:zonalstatisticsfb", 
                                                 {'INPUT':tempoBuildinglayer,
                                                  'INPUT_RASTER':build_dsm,
                                                  'RASTER_BAND':1,
                                                  'COLUMN_PREFIX':'height_',
                                                  'STATISTICS':[3],
                                                  'OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
            
            # Rename the building height attribute
            outputBuildFilepath = processing.run("native:renametablefield", 
                                                 {'INPUT':tempoBuildinglayer2,'FIELD':'height_median',
                                                  'NEW_NAME':buildingHeightField,
                                                  'OUTPUT':outputBuildFilepath})["OUTPUT"]
            
            

        # VEGETATION LAYER CREATION
        # Create the vegetation vector layer if vegetation DSM has been provided
        if veg_dsm and inputVeglayer:
            raise QgsProcessingException('A single vegetation input should be provided, either DSM or vector')
        elif veg_dsm or inputVeglayer:
            # Rasterize the DSM
            if veg_dsm:
                # Get input raster vegetation srid
                srid_vveg = veg_dsm.crs().postgisSrid()
                if not srid_vveg: 
                    feedback.pushWarning('Note that your vegetation layer has no SRID, thus the output has also no SRID')
                
                # Round raster values in order to have less vegetation polygons
                veg_dsm = processing.run("native:roundrastervalues",
                                         {'INPUT':veg_dsm,'BAND':1,
                                          'ROUNDING_DIRECTION':1,'DECIMAL_PLACES':0,
                                          'OUTPUT':'TEMPORARY_OUTPUT',
                                          'BASE_N':10})["OUTPUT"]
                # Rasterize by height value class
                    # First round raster values
                veg_dsm_rounded = processing.run("native:roundrastervalues", 
                                                 {'INPUT':veg_dsm,
                                                  'BAND':1,
                                                  'ROUNDING_DIRECTION':1,
                                                  'DECIMAL_PLACES':0,
                                                  'OUTPUT':'TEMPORARY_OUTPUT',
                                                  'BASE_N':10})["OUTPUT"]
                
                    # Then vectorized
                veg_vect = processing.run("native:pixelstopolygons", 
                                          {'INPUT_RASTER':veg_dsm_rounded,
                                           'RASTER_BAND':1,
                                           'FIELD_NAME':'VALUE',
                                           'OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
                
                    # Last, groupby and union by height values
                tempoVegFilepath = processing.run("native:dissolve",
                                                  {'INPUT':veg_vect,
                                                   'FIELD':['VALUE'],
                                                   'OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
                
                # Remove vegetation height = 0 m
                tempoVegFilepath2 = processing.run("native:extractbyattribute", 
                                                   {'INPUT':tempoVegFilepath,'FIELD':'VALUE',
                                                    'OPERATOR':2,'VALUE':'0',
                                                    'OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
                # Set the final table a projection
                tempoVegFilepath3 = processing.run("native:assignprojection", 
                                                   {'INPUT':tempoVegFilepath2,
                                                    'CRS':QgsCoordinateReferenceSystem('EPSG:{0}'.format(srid_vveg)),
                                                    'OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
            
                # Rename the vegetation height attribute
                outputVegFilepath = processing.run("native:renametablefield", 
                                                   {'INPUT':tempoVegFilepath3,'FIELD':'VALUE',
                                                    'NEW_NAME':vegetHeightField,
                                                    'OUTPUT':outputVegFilepath})["OUTPUT"]
            
            # Create vegetation patches from vegetation points
            elif inputVeglayer:
                if not radiusVegField and not heightVegField:
                    raise QgsProcessingException('At least tree crown radius or tree height attribute should be provided')
                else:
                    if radiusVegField and not heightVegField:
                        distanceExpression = 'case when {0} is null then 0 else {0} end'.format(radiusVegField)
                        heightExpression = 'case when {0} is null then 0 else {0}/{1} end'.format(radiusVegField,
                                                                                                  vegetationAspect)
                    elif not radiusVegField and heightVegField:
                        distanceExpression = 'case when {0} is null then 0 else {0}*{1} end'.format(radiusVegField,
                                                                                                    vegetationAspect)
                        heightExpression = 'case when {0} is null then 0 else {0} end'.format(heightVegField)
                    elif radiusVegField and heightVegField:
                        distanceExpression = """ case when {0} is null and {1} is null
                                                        then 0
                                                     when {0} is null and {1} is not null
                                                         then {1}*{2}
                                                     else {0} 
                                                 end
                                                """.format(radiusVegField,
                                                           heightVegField,
                                                           vegetationAspect)
                        heightExpression = """ case when {0} is null and {1} is null
                                                        then 0
                                                     when {1} is null and {0} is not null
                                                         then {0}/{2}
                                                     else {1}
                                                 end
                                                """.format(radiusVegField,
                                                           heightVegField,
                                                           vegetationAspect)
                    # Apply a buffer using radius (or height) fields                
                    tempoVegetationlayer = processing.run("native:buffer", 
                                                          {'INPUT':inputVeglayer,
                                                           'DISTANCE':QgsProperty.fromExpression(distanceExpression),
                                                           'SEGMENTS':5,'END_CAP_STYLE':0,'JOIN_STYLE':0,
                                                           'MITER_LIMIT':2,'DISSOLVE':False,
                                                           'OUTPUT':'TEMPORARY_OUTPUT'})["OUTPUT"]
                    # Calculates tree height when field do not exists or to null (using radius field)
                    outputVegFilepath = processing.run("native:fieldcalculator",
                                                       {'INPUT':tempoVegetationlayer,
                                                        'FIELD_NAME':vegetHeightField,
                                                        'FIELD_TYPE':0,'FIELD_LENGTH':0,
                                                        'FIELD_PRECISION':0,
                                                        'FORMULA':heightExpression,
                                                        'OUTPUT':outputVegFilepath})["OUTPUT"]
                
            
        # Return the output file names
        return {self.OUTPUT_BUILDING_FILE: outputBuildFilepath,
                self.OUTPUT_VEGETATION_FILE: outputVegFilepath}

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'Urban Wind Field: URock Prepare'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr(self.name())

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr(self.groupId())

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'Pre-Processor'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def shortHelpString(self):
        return self.tr('The urock_prepare is used to create building '+
                       'and vegetation polygon vector layers.'+
                       ' The output can directly be used as input of the URock plugin. '+
                       'Only a single vegetation layer should be provided as input, '+
                       'either a vegetation DSM or vegetation point data (trunk location).'
        '\n'
        '---------------\n'
        'Full manual available via the <b>Help</b>-button.')

    def helpUrl(self):
        url = "https://umep-docs.readthedocs.io/en/latest/pre-processor/Urban%20Wind%20Field%20URock%20Prepare.html"
        return url
    
    def icon(self):
        cmd_folder = Path(os.path.split(inspect.getfile(inspect.currentframe()))[0]).parent
        icon = QIcon(str(cmd_folder) + "/icons/urock.png")
        return icon

    def createInstance(self):
        return URockPrepareAlgorithm()
