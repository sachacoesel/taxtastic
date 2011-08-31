"""
taxtastic/refpkg.py

Implements an object, Refpkg, for the creation and manipulation of
reference packages for pplacer.

Note that Refpkg objects are *NOT* thread safe!
"""
from decorator import decorator
import subprocess
import itertools
import tempfile
import hashlib
import shutil
import os
import sqlite3
import copy
import json
import time
import csv

def md5file(path):
    md5 = hashlib.md5()
    with open(path) as h:
        for block in iter(lambda: h.read(4096), ''):
            md5.update(block)
    return md5.hexdigest()


def manifest_template():
    return {'metadata': {'create_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                         'format_version': '1.1'},
            'files': {},
            'md5': {},
            'log': [],
            'rollback': None,
            'rollforward': None}



@decorator
def transaction(f, self, *args, **kwargs):
    if self.current_transaction:
        f(self, *args, **kwargs)
    else:
        self.current_transaction = {'rollback': copy.deepcopy(self.contents), 
                                    'log': '(Transaction left no log message)'}
        try:
            r = f(self, *args, **kwargs)
            self.contents['log'].insert(0, self.current_transaction['log'])
            self.contents['rollback'] = copy.deepcopy(self.current_transaction['rollback'])
            self.contents['rollback'].pop('log')
            self._sync_to_disk()
            return r
        except Exception, e:
            self.contents = copy.deepcopy(self.current_transaction['rollback'])
            self.sync_to_disk()
            raise e
        finally:
            self.current_transaction = None


class Refpkg(object):
    _manifest_name = 'CONTENTS.json'

    def __init__(self, path):
        """Create a reference to a new or existing RefPkg at *path*.

        If there is already a RefPkg at *path*, a reference is
        returned to that RefPkg.  If *path* does not exist, then an
        empty RefPkg is created.
        """
        # The logic of __init__ is complicated by having to check for
        # validity of a refpkg.  Much of its can be dispatched to the
        # isvalid method, but I want that to work at any time on the
        # RefPkg object, so it must have the RefPkg's manifest already
        # in place.
        self.current_transaction = None
        self.path = os.path.abspath(path)
        if not(os.path.exists(path)):
            os.mkdir(path)
            with open(os.path.join(path, self._manifest_name), 'w') as h:
                json.dump(manifest_template(), h)
        if not(os.path.isdir(path)):
            raise ValueError("%s is not a valid RefPkg" % (path,))
        # Try to load the Refpkg and check that it's valid
        manifest_path = os.path.join(path, self._manifest_name)
        if not(os.path.isfile(manifest_path)):
            raise ValueError(("%s is not a valid RefPkg - "
                              "could not find manifest file %s") % \
                                 (path, self._manifest_name))
        with open(manifest_path) as h:
            self.contents = json.load(h)

        error = self.isinvalid()
        if error:
            raise ValueError("%s is not a valid RefPkg: %s" % (path, error))

    def _log(self, msg):
        self.current_transaction['log'] = msg

    def log(self):
        return self.contents['log']

    def isinvalid(self):
        """Check if this RefPkg is invalid.

        Valid means that it contains a properly named manifest, and
        each of the files described in the manifest exists and has the
        proper MD5 hashsum.

        If the Refpkg is valid, isinvalid returns False.  Otherwise it
        returns a nonempty string describing the error.
        """
        # Contains a manifest file
        if not(os.path.isfile(os.path.join(self.path, self._manifest_name))):
            return "No manifest file %s found" % self._manifest_name
        # Manifest file contains the proper keys
        for k in ['metadata', 'files', 'md5']:
            if not(k in self.contents):
                return "Manifest file missing key %s" % k
            if not(isinstance(self.contents[k], dict)):
                return "Key %s in manifest did not refer to a dictionary" % k

        for k in ['rollback', 'rollforward']:
            if not(k in self.contents):
                return "Manifest file missing key %s" % k
            if not(isinstance(self.contents[k], dict)) and self.contents[k] != None:
                return "Key %s in manifest did not refer to a dictionary or None" % k
        if not("log" in self.contents):
            return "Manifest file missing key 'log'"
        if not(isinstance(self.contents['log'], list)):
            return "Key 'log' in manifest did not refer to a list"
        # MD5 keys and filenames are in one to one correspondence
        if self.contents['files'].keys() != self.contents['md5'].keys():
            return ("Files and MD5 sums in manifest do not "
                    "match (files: %s, MD5 sums: %s)") % \
                    (self.contents['files'].keys(), 
                     self.contents['md5'].keys())
        # All files in the manifest exist and match the MD5 sums
        for key,filename in self.contents['files'].iteritems():
            expected_md5 = self.contents['md5'][key]
            filepath = os.path.join(self.path, filename)
            if not(os.path.exists(filepath)):
                return "File %s referred to by key %s not found in refpkg" % \
                    (filename, key)
            found_md5 = md5file(filepath)
            if found_md5 != expected_md5:
                return ("File %s referred to by key %s did "
                        "not match its MD5 sum (found: %s, expected %s)") % \
                        (found_md5, expected_md5)
        return False

    def _sync_to_disk(self):
        """Write any changes made on Refpkg to disk.

        Other methods of Refpkg that alter the contents of the package
        will call this method themselves.  Generally you should never
        have to call it by hand.  The only exception would be if
        another program has changed the Refpkg on disk while your
        program is running and you want to force your version over it.
        Otherwise it should only be called by other methods of refpkg.
        """
        with open(os.path.join(self.path, self._manifest_name), 'w') as h:
            json.dump(self.contents, h)

    def _sync_from_disk(self):
        """Read any changes made on disk to this Refpkg.

        This is necessary if other programs are making changes to the
        Refpkg on disk and your program must be synchronized to them.
        """
        with open(os.path.join(self.path, self._manifest_name)) as h:
            self.contents = json.load(h)
        error = self.isinvalid()
        if error:
            raise ValueError("Refpkg is invalid: %s" % error)

    def metadata(self, key):
        return self.contents['metadata'].get(key)

    @transaction
    def update_metadata(self, key, value):
        """Set *key* in the metadata to *value*.

        Returns the previous value of *key*, or None if the key was
        not previously set.
        """
        old_value = self.contents['metadata'].get(key)
        self.contents['metadata'][key] = value
        self._log('Updated metadata: %s=%s' % (key,value))
        return old_value

    @transaction
    def update_file(self, key, new_path):
        """Insert file *new_path* into the Refpkg under *key*.

        The filename of *new_path* will be preserved in the Refpkg
        unless it would conflict with a previously existing file, in
        which case a suffix is appended which makes it unique.  Any
        file previously referred to by *key* is deleted.
        """
        if not(os.path.isfile(new_path)):
            raise ValueError("Cannot update Refpkg with file %s" % (new_path,))
        md5_value = md5file(new_path)
        filename = os.path.basename(new_path)
        while os.path.exists(os.path.join(self.path, filename)):
            filename += "1"
        if key in self.contents['files']:
            os.unlink(os.path.join(self.path, self.contents['files'][key]))
        shutil.copyfile(new_path, os.path.join(self.path, filename))
        self.contents['files'][key] = filename
        self.contents['md5'][key] = md5_value
        self._log('Updated file: %s=%s' % (key,new_path))
        return (key, md5_value)

    def file_abspath(self, key):
        """Return the absolute path to the file referenced by *key*."""
        return os.path.join(self.path, self.file_name(key))

    def file_name(self, key):
        """Return the name of the file referenced by *key* in the refpkg."""
        if not(key in self.contents['files']):
            raise ValueError("No such resource key %s in refpkg" % key)
        return self.contents['files'][key]

    def file_md5(self, key):
        """Return the MD5 sum of the file reference by *key*."""
        if not(key in self.contents['md5']):
            raise ValueError("No such resource key %s in refpkg" % key)
        return self.contents['md5'][key]

    @transaction
    def reroot(self, rppr=None, pretend=False):
        """Reroot the phylogenetic tree in the Refpkg."""
        fd, name = tempfile.mkstemp()
        os.close(fd)
        try:
            # Use a specific path to rppr, otherwise rely on $PATH
            subprocess.check_call([rppr or 'rppr', 'reroot',
                                   '-c', self.path, '-o', name])
            if not(pretend):
                self.update_file('tree', name)
        finally:
            os.unlink(name)
        self._log('Rerooting refpkg')
        
    def update_phylo_model(self, raxml_stats):
        fd, name = tempfile.mkstemp()
        os.close(fd)
        try:
            with open(name, 'w') as phylo_model, open(raxml_stats) as h:
                json.dump(utils.parse_raxml(h), phylo_model)
            self.update_file('phylo_model', name)
        finally:
            os.unlink(name)

    def rollback(self):
        # Pull out log, put top entry in rollforward along with current JSON
        # Copy top of rollback to current, and insert rest of log into it
        if self.contents['rollback'] == None:
            raise ValueError("No operation to roll back on refpkg")
        future_msg = self.contents['log'][0]
        rolledback_log = self.contents['log'][1:]
        rollforward = copy.deepcopy(self.contents)
        rollforward.pop('rollback')
        self.contents = self.contents['rollback']
        self.contents[u'log'] = rolledback_log
        self.contents[u'rollforward'] = [future_msg, rollforward]

    def rollforward(self):
        if self.contents['rollforward'] == None:
            raise ValueError("No operation to roll forward on refpkg")
        new_log_message = self.contents['rollforward'][0]
        new_contents = self.contents['rollforward'][1]
        new_contents[u'log'] = [new_log_message] + self.contents['log']
        self.contents.pop('log')
        self.contents['rollforward'] = None
        new_contents[u'rollback'] = copy.deepcopy(self.contents)
        self.contents = new_contents
