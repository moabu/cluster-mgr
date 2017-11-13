import codecs
import os
import re
from setuptools import setup
from setuptools import find_packages


def find_version(*file_paths):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, *file_paths), 'r') as f:
        version_file = f.read()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                              version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


setup(
    name='clustermgr',
    author="Gluu",
    author_email="support@gluu.org",
    url="https://github.com/GluuFederation/cluster-mgr/",
    version=find_version("clustermgr", "__init__.py"),
    packages=find_packages(exclude=["e2e", "tests"]),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        "flask<=0.12",  # loose pin as a workaround for setuptools issue
        "flask-wtf",
        "celery",
        "flask-sqlalchemy",
        "redis",
        "requests",
        "flask-migrate",
        "ldap3",
        "paramiko",
        "cryptography",
        "ipaddress",
        "enum34",
    ],
    entry_points={
        "console_scripts": ["clustermgr-cli=clusterapp:cli",
                            "clustermgr-celery=clusterapp:run_celery"],
    },
    scripts=['clusterapp.py'],
)
