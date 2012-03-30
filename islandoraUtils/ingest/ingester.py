'''
Created on 2012-03-19

@author: William Panting
@TODO: properties configuration and logger, also accept overrides for all objects used in constructor
@TODO: look into default PID namespace
@TODO: a function for creating/deleting the tmp dir
'''
import os

from fcrepo.connection import Connection, FedoraConnectionException
from fcrepo.client import FedoraClient

from islandoraUtils.ingest.Islandora_configuration import Islandora_configuration
from islandoraUtils.ingest.Islandora_logger import Islandora_logger
from islandoraUtils.ingest.Islandora_cron_batch import Islandora_cron_batch
from islandoraUtils.ingest.Islandora_alerter import Islandora_alerter
from islandoraUtils.metadata import fedora_relationships
from islandoraUtils.misc import get_mime_type_from_path, path_to_datastream_ID

class ingester(object):
    '''
    This is the kingpin.  This object should handle creating all the other basic ingest helpers.
    @TODO: add namespace and fcrepo properties
    '''


    def __init__(self, configuration_file_path, default_Fedora_namespace=None, is_a_cron=False, Islandora_configuration_object=None, Islandora_logger_object=None, Islandora_alerter_object=None, Islandora_cron_batch_object=None):
        '''
        Get all the objects that are likely to be used for an ingest
        @param configuration_file_path: where the configuration for the ingest can be found
        @param last_time_ran: the last time this ingest was ran (if this is set a cron_batch object is created with the information)
        '''
        
        #configuration and logger have intermediate objects
        if not Islandora_configuration_object:
            my_Islandora_configuration = Islandora_configuration(configuration_file_path)
        else:
            my_Islandora_configuration = Islandora_configuration_object
        
        if not Islandora_logger_object:
            my_Islandora_logger = Islandora_logger(my_Islandora_configuration)
        else:
            my_Islandora_logger = Islandora_logger_object
        
        self._configuration = my_Islandora_configuration.configuration_dictionary
        
        self._logger = my_Islandora_logger.logger
        
        #set the class properties
        if not Islandora_alerter_object:
            self._alerter = Islandora_alerter(my_Islandora_configuration, self._logger)
        else:
            self._alerter = Islandora_alerter_object
        
        if is_a_cron:
            if not Islandora_cron_batch_object:
                self._cron_batch = Islandora_cron_batch(my_Islandora_configuration)
            else:
                self._cron_batch = Islandora_cron_batch_object
            
        #Fedora connection through fcrepo, should not be done before custom logger because the first settings on root logger are immutable
        self._fcrepo_connection = Connection(self._configuration['Fedora']['url'],
                        username=self._configuration['Fedora']['username'],
                         password=self._configuration['Fedora']['password'])
        try:
            self._Fedora_client = FedoraClient(self._fcrepo_connection)
        except FedoraConnectionException:
            self._logger.error('Error connecting to Fedora')
        
        if not default_Fedora_namespace:#unicode because of fcrepo
            self._default_Fedora_namespace = unicode(self._configuration['miscellaneous']['default_fedora_pid_namespace'])#no caps in configParser
        else:
            self._default_Fedora_namespace = unicode(default_Fedora_namespace)
            
        
        #pyrelationships 
        self._Fedora_model_namespace = fedora_relationships.rels_namespace('fedora-model','info:fedora/fedora-system:def/model#')
        
    @property
    def alerter(self):
        '''
        Returns the alerter that this object creates
        '''
        return self._alerter           

    @property
    def logger(self):
        '''
        Returns the logger that this object creates
        '''
        return self._logger
    
    @property
    def configuration(self):
        '''
        The dictionary version of the ingest's configuration.
        '''
        return self._configuration
    
    @property
    def cron_batch(self):
        '''
        returns the batch job.
        '''
        return self._cron_batch
    
    @property
    def Fedora_model_namespace(self):
        '''
        returns the namespace object for ('fedora-model','info:fedora/fedora-system:def/model#')
        '''
        return self._Fedora_model_namespace
    
    @property
    def Fedora_client(self):
        '''
        returns the fcrepo client object
        '''
        return self._Fedora_client
    
    @property
    def default_Fedora_namespace(self):
        '''
        returns the default namespace to ingest fedora objects into
        '''
        return self._default_Fedora_namespace
    
    def ingest_object(self, PID=None, object_label=None, archival_datastream=None, metadata_datastream=None, datastreams=[], collections=[], content_models=[]):
        '''
        This function will ingest an object with a single metadata and archival datastream with a specified set of relationships
        it will use our best practices for logging and assume the use of microservices for derivatives and their RELS-INT management
        it will overwrite a pre-existing object if one exists
        this function can be extended later, the initial write is for an atomistic content model with 'sensible' defaults
        mimetypes are detected using islandoraUtils for compatibility with Islandora
        @TODO: look at taking in a relationship object
        @TODO: add a parameter for datastreams=[] that is a list of dictionaries mimicking the dictionary in archival_datastream and metadata_datastream
        @param PID: The PID of the object to create or update. If non is supplied then getNextPID is used
        @param archival_datastream: an image, audio, whatever file path will be a managed datastream
        [{'path':'./objectstuff'}]
        @param metadata_file_path: will be inline xml
        @param collection: the PID of the collection so RELS-EXT can be created
        @param content_model: The PID of the content_model so the RELS-EXT can be created
        @return PID: The PID of the object created or updated.
        
        default labels: 'Canonical Metadata' 'Primary Datastream'
        '''
        Fedora_object = None  
        #normalize parameters to a list of dictionaries of what datastreams to ingest
        if isinstance(archival_datastream, str):
            archival_datastream_dict = {'source_file':archival_datastream,
                                        'label':os.path.basename(archival_datastream),
                                        'mime_type':get_mime_type_from_path(archival_datastream),
                                        'datastream_ID':path_to_datastream_ID(archival_datastream)}
            datastreams.append(archival_datastream_dict)
        if isinstance(metadata_datastream, str):
            metadata_datastream_dict = {'source_file':metadata_datastream,
                                        'label':os.path.basename(metadata_datastream),
                                        'mime_type':get_mime_type_from_path(metadata_datastream),
                                        'datastream_ID':path_to_datastream_ID(metadata_datastream)}
            datastreams.append(metadata_datastream_dict)
            
        #encode in unicode because that's what fcrepo needs
        object_label = unicode(object_label)
        
        #set up the Fedora object PID
        if not PID:
            PID = self._Fedora_client.getNextPID(self._default_Fedora_namespace)
            Fedora_object = self._Fedora_client.createObject(PID, label = object_label)
            
        #creating vs updating
        if not Fedora_object:
            try:
                Fedora_object = self._Fedora_client.getObject(PID)
            except FedoraConnectionException, object_fetch_exception:
                print(object_fetch_exception.httpcode)
                if object_fetch_exception.httpcode in [404]:
                    self._logger.info(PID + ' missing, creating object.\n')
                    Fedora_object = self._Fedora_client.createObject(PID, label = object_label)
                else:
                    self._logger.error(PID + ' was not created successfully.')
                
        #loop through datastreams adding them to inline or managed based on mimetype
        if datastreams:
            pass
        #add the appropriate relations to the object
        '''
        # adding an inline xml stream
        try:
            book_object.addDataStream(u'MODS', unicode(mods_contents), label = u'MODS',
            mimeType = u'text/xml', controlGroup = u'X',
            logMessage = u'Added basic mods meta data.')
            logging.info('Added MODS datastream to:' + book_pid)
        except FedoraConnectionException:
            logging.error('Error in adding MODS datastream to:' + book_pid + '\n')
        
        # adding a binary stream
        book_name = mods_file[:mods_file.find('_')]
            pdf_file = book_name + '.pdf'
            pdf_file_path = os.path.join(source_directory, 'images-pdf', pdf_file)
            pdf_file_handle = open(pdf_file_path, 'rb')
            
            try:
                book_object.addDataStream(u'PDF', u'aTmpStr', label=u'PDF',
                mimeType = u'application/pdf', controlGroup = u'M',
                logMessage = u'Added PDF datastream.')
                datastream = book_object['PDF']
                datastream.setContent(pdf_file_handle)
                logging.info('Added PDF datastream to:' + book_pid)
            except FedoraConnectionException:
                logging.error('Error in adding PDF datastream to:' + book_pid + '\n')
            pdf_file_handle.close()
            
            '''
        #write relationships to the object
        objRelsExt = fedora_relationships.rels_ext(Fedora_object, self._Fedora_model_namespace)
        should_update_RELS_EXT = False
        
        for collection in collections:
            #remove relationship if it exists
            if objRelsExt.getRelationships(predicate='isMemberOfCollection'):
                objRelsExt.purgeRelationships(predicate='isMemberOfCollection')
            
            objRelsExt.addRelationship('isMemberOfCollection', unicode(collection))
            should_update_RELS_EXT = True
        
        for content_model in content_models:
            if objRelsExt.getRelationships(predicate=fedora_relationships.rels_predicate('fedora-model','hasModel')):
                objRelsExt.purgeRelationships(predicate=fedora_relationships.rels_predicate('fedora-model','hasModel'))
            
            objRelsExt.addRelationship(fedora_relationships.rels_predicate('fedora-model','hasModel'), unicode(content_model))
            should_update_RELS_EXT = True
            
        if should_update_RELS_EXT: 
            objRelsExt.update()
        