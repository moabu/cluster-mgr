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
    description="Tool to facilitate LDAP replication, key management and log centralization for the Gluu Server",
    long_description="See project `README <https://github.com/GluuFederation/cluster-mgr>`_ for details.",
    version=find_version("clustermgr", "__init__.py"),
    packages=find_packages(exclude=["e2e", "tests"]),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        "vine",
        "MarkupSafe>=0.23",
        "kombu==4.5",
        "billiard==3.6",
        "cffi",
        "asn1crypto",
        "blinker",
        "pynacl",
        "pyasn1",
        "bcrypt",
        "alembic",
        "WTForms",
        "Flask",
        "Flask-WTF",
        "celery",
        "Flask-SQLAlchemy",
        "redis==3.2.0",
        "requests>=2.20.0",
        "Flask-Migrate",
        "ldap3",
        "paramiko>=2.4.0",
        "pyOpenSSL==19.0.0",
        "Flask-Login",
        "Flask-Mail",
        "cryptography",
        "ipaddress",
        "enum34",
        "oxdpython",
        "influxdb",
        'gunicorn',
        'psutil',
    ],
    scripts=['clusterapp.py', 'clustermgr-cli'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Flask',
        'Intended Audience :: System Administrators',
        'License :: Other/Proprietary License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 2 :: Only',
        'Topic :: System :: Logging',
        'Topic :: System :: Monitoring',
        'Topic :: System :: Systems Administration'
    ],
    license='All Rights Reserved',
)
