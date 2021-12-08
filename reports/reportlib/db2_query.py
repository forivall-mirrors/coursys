from .query import Query
from django.conf import settings
from coredata.queries import SIMSProblem

from . import semester
import datetime

class Unescaped(str):
    """ This string won't be escaped when used as an argument.

    >>> DB2_Query.clean_input("hello") 
    "'hello'"
    >>> DB2_Query.clean_input(Unescaped("hello"))
    'hello'

    """

    pass

class UnknownArgumentType(Exception):
    """ An argument has been passed to a DB2 query that we don't understand. """
    pass

class NotConnected(Exception):
    """ We've not yet connected to DB2.  Call DB2_Query.connect(options) to connect. """
    pass


class DB2_Query(Query):
    
    db = False
    
    @staticmethod
    def connect():
        """ Connect to the CSRPT database. [Which isn't actually DB2 anymore]

            All subclasses of DB2_Query will use this database for queries. 

        """

        if settings.DISABLE_REPORTING_DB:
            raise SIMSProblem("Reporting database access has been disabled in this deployment.")

        import pyodbc
        dbconn = pyodbc.connect("DRIVER={FreeTDS};SERVER=%s;PORT=1433;DATABASE=%s;Trusted_Connection=Yes"
                                % (settings.SIMS_DB_SERVER, settings.SIMS_DB_NAME))
        DB2_Query.db = dbconn


    def __init__(self, query_args={}):
        if not self.db:
            raise NotConnected("Please call DB2_Query.connect before creating any DB2 query objects.")
        super(DB2_Query, self).__init__(self.db, DB2_Query.clean_input, DB2_Query.clean_output, query_args)

    def result(self):
        return super(DB2_Query, self).result()

    @staticmethod
    def clean_input( argument ):
        """ Given an object of unknown type, return a string that can be used in the database. 

        Doesn't (yet) perform proper database sanitization. DB injection still possible. 
        But it's a readonly database and front-end users have no access to the query arguments. 

        >>> DB2_Query.clean_input("hello") 
        "'hello'"
        >>> DB2_Query.clean_input(83)
        '83'
        >>> DB2_Query.clean_input( datetime.datetime( 2012, 7, 23 ) )
        "DATE('2012-7-23')"
        >>> DB2_Query.clean_input( ["hello", 83, datetime.datetime( 2012, 7, 23) ] )
        "('hello',83,DATE('2012-7-23'))"
        >>> DB2_Query.clean_input( [1127] ) 
        '(1127)'
        """
        if type( argument ) is str: 
            return DB2_Query.clean_string( argument )
        if type( argument ) is str:
            return DB2_Query.clean_unicode( argument )
        if type( argument ) is Unescaped:
            return argument
        if type( argument ) is int:
            return DB2_Query.clean_int( argument )
        if type( argument ) is datetime.datetime:
            return DB2_Query.clean_datetime( argument )
        if type( argument ) is semester.Semester:
            return DB2_Query.clean_int( argument )
        if type( argument ) is list: 
            return DB2_Query.clean_list( argument )
        else:
            raise UnknownArgumentType( str(argument) + " is of type " + str(type(argument)) ) 

    @staticmethod
    def clean_output(argument):
        if type( argument ) is str: 
            return argument.strip()
        else:
            return argument

    @staticmethod
    def clean_string(arg):
        return "\'"+arg+"\'"

    @staticmethod
    def clean_unicode(arg):
        return "\'"+arg.encode("utf-8")+"\'"

    @staticmethod
    def clean_int(arg):
        return str( arg )

    @staticmethod
    def clean_datetime(arg): 
        return "'%s-%s-%s'" % (arg.year, arg.month, arg.day)

    @staticmethod
    def clean_list(list_of_arguments):
        return "(" + ",".join( [DB2_Query.clean_input(arg) for arg in list_of_arguments] ) + ")"

