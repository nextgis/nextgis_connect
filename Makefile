# This script now only for update translations in submodule
#
SRC_FILES = `find . ! -path "./src/nextgis_connect/ngw_api/*" \( -name "*.ui" -o -name "*.py" \) | tr "\n" " "`
SRC2_FILES = `find ./src/nextgis_connect/ngw_api/qgis/ -name "*.ui" -o -name "*.py" | tr "\n" " "`

TS_FILE = src/nextgis_connect/i18n/*.ts
TS2_FILE = src/nextgis_connect/ngw_api/qgis/i18n/*.ts

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
