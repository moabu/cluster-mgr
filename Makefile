.DEFAULT_GOAL := develop

develop:
	/usr/bin/env python3 setup.py develop

install:
	pip3 install .

uninstall:
	pip3 uninstall clustermgr4 -y

zipapp:
	shiv --compressed -o clustermgr4-4.pyz -p '/usr/bin/env python3' -c clusterapp.py . --no-cache
