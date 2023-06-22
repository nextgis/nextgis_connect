SRC_FILES = `find . ! -path "./src/ngw_api/*" \( -name "*.ui" -o -name "*.py" \) | tr "\n" " "`
SRC2_FILES = `find ./src/ngw_api/qgis/ -name "*.ui" -o -name "*.py" | tr "\n" " "`

TS_FILE = src/i18n/*.ts
TS2_FILE = src/ngw_api/qgis/i18n/*.ts

BUILD_DIR=/tmp/build_plugin
PLUGIN_NAME=nextgis_connect

update_ts:
	pylupdate5 -noobsolete $(SRC_FILES) -ts $(TS_FILE)
	pylupdate5 -noobsolete $(SRC2_FILES) -ts $(TS2_FILE)
	@echo "TS files have been updated!"

	@for file in $(TS_FILE) $(TS2_FILE) ; do \
		str_to_update=`grep -c 'type="unfinished"' $$file`; \
		if [ $$str_to_update -gt 0 ]; then \
			echo "Need to retranslate: $$file ($$str_to_update string(s))"; \
		fi \
	done


compile_ts:
	lrelease $(TS_FILE) $(TS2_FILE)

clean:
	py3clean .

release: compile_ts clean
	mkdir -p $(BUILD_DIR)/$(PLUGIN_NAME)

	cp -r src/* LICENSE $(BUILD_DIR)/$(PLUGIN_NAME)
	rm -rf `find $(BUILD_DIR)/$(PLUGIN_NAME) -name '__pycache__'`
	rm -rf `find $(BUILD_DIR)/$(PLUGIN_NAME) -name '.git' -o -name '.gitignore'`
	cd $(BUILD_DIR) && zip -9r $(PLUGIN_NAME).zip $(PLUGIN_NAME)
	mv $(BUILD_DIR)/$(PLUGIN_NAME).zip .

	rm -r $(BUILD_DIR)/$(PLUGIN_NAME)
