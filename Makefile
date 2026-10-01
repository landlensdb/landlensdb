# QGIS
qgis-build:
#	@cp dist/*.whl qgis_plugin_landlensdb
	PYTHONPATH=. $(BUILD_PLUGIN)
	@echo "Generating plugin requirements.txt..."
	python qgis_plugin_landlensdb/build_plugin.py
	@echo "Copying landlensdb into plugin folder..."
	cp -R landlensdb qgis_plugin_landlensdb/
	@echo "Copying plugin icon into plugin folder..."
	cp docs/images/landlensdb.png qgis_plugin_landlensdb/landlensdb.png
	@echo "Removing __pycache__..."
	find qgis_plugin_landlensdb -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "Creating plugin zip..."
	rm -f qgis_plugin_landlensdb.zip
	zip -r qgis_plugin_landlensdb.zip qgis_plugin_landlensdb/ \
	  -x "*.DS_Store" "*__MACOSX*" "*__pycache__*" "*.pyc"
	@echo "Removing copied landlensdb folder from plugin workspace..."
	rm -rf qgis_plugin_landlensdb/landlensdb
