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
    name='clustermgr4',
    author="Gluu",
    author_email="support@gluu.org",
    url="https://github.com/GluuFederation/cluster-mgr/tree/4.0/clustermgr",
    description="Tool to facilitate LDAP replication, key management and log centralization for the Gluu Server",
    long_description="See project `README <https://github.com/GluuFederation/cluster-mgr>`_ for details.",
    version=find_version("clustermgr/version.py"),
    packages=find_packages(exclude=["e2e", "tests"]),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        'flask',
        'gunicorn',
        'celery',
        'flask-sqlalchemy',
        'flask-migrate',
        'flask-mail',
        'flask-login',
        'flask-wtf',
        'redislite',
        'requests',
        'cryptography',
        'paramiko',
        'email-validator',
        'ldap3',
        'influxdb',
    ],
    scripts=['clusterapp.py', 'clustermgr4-cli'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Flask',
        'Intended Audience :: System Administrators',
        'License :: Other/Proprietary License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: System :: Logging',
        'Topic :: System :: Monitoring',
        'Topic :: System :: Systems Administration'
    ],
    license='All Rights Reserved',
)
