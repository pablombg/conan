import os
import shutil
import unittest
from collections import namedtuple

from conans.client.cmd.export import _replace_scm_data_in_conanfile
from conans.client.loader import _parse_conanfile
from conans.client.tools import chdir
from conans.model.ref import ConanFileReference
from conans.model.scm import SCMData
from conans.test.utils.test_files import temp_folder
from conans.test.utils.tools import TestClient, TestServer, TurboTestClient
from conans.util.files import load, save


class ExportTest(unittest.TestCase):

    def export_warning_test(self):
        mixed_conanfile = """
from conans import ConanFile

class HelloConan(ConanFile):
    name = "Hello"
    version = "0.1"
    exports = "*.h", "*.cpp"
    settings = "os", "os_build"
    def package(self):
        self.copy("*.h", "include")
"""
        client = TestClient()
        client.save({"conanfile.py": mixed_conanfile})
        client.run("export . Hello/0.1")
        self.assertIn("This package defines both 'os' and 'os_build'", client.out)

    def export_no_warning_test(self):
        conanfile = """
from conans import ConanFile

class HelloConan(ConanFile):
    name = "Hello"
    version = "0.1"
    exports = "*.h", "*.cpp"
    settings = "os"
    def package(self):
        self.copy("*.h", "include")
"""
        client = TestClient()
        client.save({"conanfile.py": conanfile})
        client.run("export . Hello/0.1")
        self.assertNotIn("This package defines both 'os' and 'os_build'", client.out)


class ReplaceSCMDataInConanfileTest(unittest.TestCase):
    conanfile = """
from conans import ConanFile

class ConanLib(ConanFile):
    name = "lib"
    version = "0.1"
    scm = {{"revision": "{revision}",
           "type": "git",
           "url": "{url}"}}

    {after_scm}

{after_recipe}
"""

    def run(self, *args, **kwargs):
        self.tmp_folder = temp_folder()
        self.conanfile_path = os.path.join(self.tmp_folder, 'conanfile.py')
        try:
            super(ReplaceSCMDataInConanfileTest, self).run(*args, **kwargs)
        finally:
            shutil.rmtree(self.tmp_folder)

    def _do_actual_test(self, scm_data, after_scm, after_recipe):
        target_conanfile = self.conanfile.format(url=scm_data['url'],
                                                 revision=scm_data['revision'],
                                                 after_scm=after_scm,
                                                 after_recipe=after_recipe)
        save(self.conanfile_path, content=self.conanfile.format(url='auto', revision='auto',
                                                                after_scm=after_scm,
                                                                after_recipe=after_recipe))
        scm_data = SCMData(conanfile=namedtuple('_', 'scm')(scm=scm_data))
        _replace_scm_data_in_conanfile(self.conanfile_path, scm_data)
        self.assertEqual(load(self.conanfile_path), target_conanfile)
        # Check that the resulting file is valid python code.
        _parse_conanfile(conan_file_path=self.conanfile_path)

    def test_conanfile_after_scm(self):
        scm_data = {'type': 'git',
                    'url': 'url_value',
                    'revision': 'revision_value'}
        after_scm = 'attrib = 23'
        after_recipe = ''
        self._do_actual_test(scm_data=scm_data, after_scm=after_scm, after_recipe=after_recipe)

    def test_conanfile_after_scm_and_recipe(self):
        scm_data = {'type': 'git',
                    'url': 'url_value',
                    'revision': 'revision_value'}
        after_scm = 'attrib = 23'
        after_recipe = 'another = 23'
        self._do_actual_test(scm_data=scm_data, after_scm=after_scm, after_recipe=after_recipe)

    def test_conanfile_after_recipe(self):
        scm_data = {'type': 'git',
                    'url': 'url_value',
                    'revision': 'revision_value'}
        after_scm = ''
        after_recipe = 'another = 23'
        self._do_actual_test(scm_data=scm_data, after_scm=after_scm, after_recipe=after_recipe)

    def test_conanfile_none(self):
        scm_data = {'type': 'git',
                    'url': 'url_value',
                    'revision': 'revision_value'}
        after_scm = ''
        after_recipe = ''
        self._do_actual_test(scm_data=scm_data, after_scm=after_scm, after_recipe=after_recipe)

    def scm_from_superclass_test(self):
        client = TurboTestClient()
        conanfile = '''from conans import ConanFile

def get_conanfile():

    class BaseConanFile(ConanFile):
        scm = {
            "type": "git",
            "url": "auto",
            "revision": "auto"
        }

    return BaseConanFile

class Baseline(ConanFile):
    name = "Base"
    version = "1.0.0"
'''
        client.init_git_repo({"conanfile.py": conanfile}, origin_url="http://whatever.com/c.git")
        client.run("export . conan/stable")
        conanfile1 = """from conans import ConanFile, python_requires, tools

baseline = "Base/1.0.0@conan/stable"

# recipe inherits properties from the conanfile defined in the baseline
class ModuleConan(python_requires(baseline).get_conanfile()):
    name = "module_name"
    version = "1.0.0"
"""
        conanfile2 = """from conans import ConanFile, python_requires, tools

baseline = "Base/1.0.0@conan/stable"

# recipe inherits properties from the conanfile defined in the baseline
class ModuleConan(python_requires(baseline).get_conanfile()):
    pass
"""

        for conanfile in [conanfile1, conanfile2]:
            client.save({"conanfile.py": conanfile})
            # Add and commit so it do the scm replacements correctly
            client.run_command("git add .")
            client.run_command('git commit -m  "commiting"')
            client.run("export . module_name/1.0.0@conan/stable")
            self.assertIn("module_name/1.0.0@conan/stable: "
                          "A new conanfile.py version was exported", client.out)
            ref = ConanFileReference.loads("module_name/1.0.0@conan/stable")
            contents = load(os.path.join(client.cache.package_layout(ref).export(),
                                         "conanfile.py"))
            class_str = 'class ModuleConan(python_requires(baseline).get_conanfile()):\n'
            self.assertIn('%s    scm = {"revision":' % class_str, contents)


class SCMUpload(unittest.TestCase):

    def scm_sources_test(self):
        """ Test conan_sources.tgz is deleted in server when removing 'exports_sources' and using
        'scm'"""
        conanfile = """from conans import ConanFile
class TestConan(ConanFile):
    name = "test"
    version = "1.0"
"""
        exports_sources = """
    exports_sources = "include/*"
"""
        servers = {"upload_repo": TestServer([("*/*@*/*", "*")], [("*/*@*/*", "*")],
                                             users={"lasote": "mypass"})}
        client = TestClient(servers=servers, users={"upload_repo": [("lasote", "mypass")]})
        client.save({"conanfile.py": conanfile + exports_sources, "include/file": "content"})
        client.run("create . danimtb/testing")
        client.run("upload test/1.0@danimtb/testing -r upload_repo")
        self.assertIn("Uploading conan_sources.tgz", client.out)
        ref = ConanFileReference("test", "1.0", "danimtb", "testing")
        rev = servers["upload_repo"].server_store.get_last_revision(ref).revision
        ref = ref.copy_with_rev(rev)
        export_sources_path = os.path.join(servers["upload_repo"].server_store.export(ref),
                                           "conan_sources.tgz")
        self.assertTrue(os.path.exists(export_sources_path))

        scm = """
    scm = {"type": "git",
           "url": "auto",
           "revision": "auto"}
"""
        client.save({"conanfile.py": conanfile + scm})
        client.run_command("git init")
        client.run_command('git config user.email "you@example.com"')
        client.run_command('git config user.name "Your Name"')
        client.run_command("git remote add origin https://github.com/fake/fake.git")
        client.run_command("git add .")
        client.run_command("git commit -m \"initial commit\"")
        client.run("create . danimtb/testing")
        self.assertIn("Repo origin deduced by 'auto': https://github.com/fake/fake.git", client.out)
        client.run("upload test/1.0@danimtb/testing -r upload_repo")
        self.assertNotIn("Uploading conan_sources.tgz", client.out)
        rev = servers["upload_repo"].server_store.get_last_revision(ref).revision
        ref = ref.copy_with_rev(rev)
        export_sources_path = os.path.join(servers["upload_repo"].server_store.export(ref),
                                           "conan_sources.tgz")
        self.assertFalse(os.path.exists(export_sources_path))
