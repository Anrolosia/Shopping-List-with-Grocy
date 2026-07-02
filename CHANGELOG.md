# Changelog

All notable changes to this project will be documented in this file.

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.26.3] - 2026-07-02

### 🐛 Bug Fixes

- Bypassed pytest-socket on windows dev machines and automated release version bumping via git-cliff
- Fixed null product_id crash in parse_products and add_product_to_grocy_shopping_list (#74)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.26.2] - 2026-04-09

### 🐛 Bug Fixes

- Persist enable_product_sensors in config flow and add missing translations

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.26.1] - 2026-04-09

### 🐛 Bug Fixes

- Add missing enable_product_sensors field to config flow options schema

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.26.0] - 2026-04-09

### ✨ Features

- Add selection criteria for bidirectional sync with ruff fixes and regression guards (via PR #66 by marcomag89)
- Add selection criteria for bidirectional sync (via PR #66 by marcomag89)
- Add enable_product_sensors config option (via PR #65 by marcomag89)
- Add Italian translations (via PR #64 by marcomag89)

### 🐛 Bug Fixes

- Rename config_entry to _stored_config_entry in OptionsFlow to avoid read-only property conflict

### ⚙️ Miscellaneous

- Add new contributors detection to release notes

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.25.2] - 2026-04-09

### ⚙️ Miscellaneous

- Replace git-cliff with pure bash git log for release notes generation

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.25.1] - 2026-04-09

### ⚙️ Miscellaneous

- Replace git-cliff-action with direct binary install to fix Docker build failure

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.25.0] - 2026-04-09

### 🐛 Bug Fixes

- Replace inline Python bump with external script to fix Windows indentation error
- Fixed issue with voice assistant blueprint (#72)
- Fixed issue when adding shopping list items with no product (#73)

### 🚜 Refactor

- Robustness pass — deduplicate cleanup, fix migration guards, correct log levels and anti-patterns

### 🧪 Testing

- Add initial test suite covering utils, API pure methods and ML engine

### ⚙️ Miscellaneous

- Modernize release workflow — git-cliff v3, deprecate set-output, tag-driven release

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.24.4] - 2026-02-09

### 🎨 Styling

- Apply code formatting (black/isort)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.24.3] - 2026-02-09

### ✨ Features

- Add option to disable voice assistant notifications #63

### 🐛 Bug Fixes

- Move blueprint copy to executor to prevent blocking event loop #71

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.24.2] - 2026-02-09

### 🐛 Bug Fixes

- Fixed OptionsFlow compatibility with recent Home Assistant versions

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.24.1] - 2025-10-13

### ✨ Features

- Updated product attributes to add 'best_before_date' and 'purchase_date'

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.24.0] - 2025-09-10

### 🐛 Bug Fixes

- Fixed compatibility with Home Assistant 2025.09.x

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.23.2] - 2025-08-09

### 🐛 Bug Fixes

- Always expose localized sync_not_enabled in voice_response_helper sensor, use correct Jinja pattern in blueprint, and add missing config translation key

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.23.1] - 2025-08-08

### ✨ Features

- Voice assistant integration for seamless todo-grocy sync (closes #59)

### 🐛 Bug Fixes

- Fixed quantity not taken into account in suggestion panel

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.22.1] - 2025-08-01

### ⚙️ Miscellaneous

- Removed development files

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.22.0] - 2025-07-31

### ✨ Features

- Add AI-powered shopping suggestions with statistical analysis engine

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.21.0] - 2025-07-17

### ⚙️ Miscellaneous

- Removed deprecated MQTT requirement

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.20.2] - 2025-07-17

### 🐛 Bug Fixes

- Fixed issue during init when MQTT options are not provided

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.20.1] - 2025-06-29

### 🐛 Bug Fixes

- Fixed compatibility with HA 2026.6.x and prevent rollback to previous state (#61)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.20.0] - 2025-04-07

### ✨ Features

- Changed Qty in stock, Qty opened and Qty unopened from int to float. Fixed Qty opened logic (#57)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.7] - 2025-03-18

### 🐛 Bug Fixes

- Fixed wrongly calculated quantities (#53)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.6] - 2025-03-18

### 🐛 Bug Fixes

- Added a failsafe to prevent wrongly calculated quantities (#53)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.5] - 2025-03-16

### Bug

- Fixed issue where a shopping list removed from Grocy was never removed from Home Assistant (#53)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.4] - 2025-03-10

### 🐛 Bug Fixes

- Fixed timeout issue on migration (#51)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.3] - 2025-03-10

### 🚜 Refactor

- Improved code to better handle compatibility with self hosted Grocy instance and Home Assistant Grocy addon

### ⚙️ Miscellaneous

- *(release)* Prepare for v0.19.3

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.2] - 2025-03-07

### ✨ Features

- Adding an option in config to disable timeout on network calls and data processing.

### 🐛 Bug Fixes

- Wait for migration to complete
- Prevent todo class to be initialized multiple times

### 🚜 Refactor

- Optimized code for better sensor management

### ⚙️ Miscellaneous

- *(release)* Prepare for v0.19.2

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.1] - 2025-03-04

### 🐛 Bug Fixes

- Notify hass if an entity is changed to refresh card

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.19.0] - 2025-03-04

### ✨ Features

- Entities are now created using HomeAssistant native way

### 🐛 Bug Fixes

- Fixed url validation regex issue (#47)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.18.0] - 2025-03-01

### ✨ Features

- Added shopping list completion and deletion features

### ⚡ Performance

- Refactored code to increase performance and add logs

### 📚 Documentation

- Updated documentation to a better format

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.17.0] - 2025-02-26

### ✨ Features

- Added integration with Home Assistant todo lists (#45)

### 📚 Documentation

- Updated README.md file

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.16.4] - 2025-02-19

### 🚜 Refactor

- Fixing logging

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.16.3] - 2025-02-19

### 🚜 Refactor

- Adjust logging to avoid false positive

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.16.2] - 2025-02-19

### 🚜 Refactor

- Adding MQTT logs to help debugging connexion issues

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.16.1] - 2025-02-17

### 🚜 Refactor

- Changed state attributes return value

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.16.0] - 2025-02-16

### 🚜 Refactor

- [**breaking**] Removed "Add all products in sensor attributes" option
- Updating cliff library

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.15.0] - 2024-12-07

### 📚 Documentation

- Update README with new integration card

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.14.1] - 2024-10-19

### 🚜 Refactor

- Replaced deprecated async_forward_entry_setup call

### Release

- Prepare for 0.14.1

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.14.0] - 2023-11-19

### ✨ Features

- Added qty_unopened attribute (#37)

### Release

- Prepare for 0.14.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.13.1] - 2023-11-05

### ✨ Features

- Added consume location as attribute (#36)

### 📚 Documentation

- Updated documentation titles

### Release

- Prepare for 0.13.1

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.13.0] - 2023-11-04

### ✨ Features

- Added opened stock tracking, including aggregated opened tracking for sub-products
- Added quantity unit Stock and Purchase as string for each product (#34)

### 📚 Documentation

- Updated documentation to add Known issues / FAQ section

### Release

- Prepare for 0.13.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.12.1] - 2023-10-31

### 🐛 Bug Fixes

- Removed logs

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.12.0] - 2023-10-31

### ✨ Features

- Aggregated quantity for parent product (#32)

### Release

- Prepare for 0.12.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.11.0] - 2023-10-17

### ✨ Features

- Added Grocy's API product fields (#30)

### Release

- Prepare for 0.11.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.10.3] - 2023-09-25

### ⚙️ Miscellaneous

- Updated scripts

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.10.2] - 2023-09-25

### ⚙️ Miscellaneous

- Updated scripts

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.10.1] - 2023-09-25

### 📚 Documentation

- Updated documentation for userfields example

### Release

- Prepare for 0.10.1

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.10.0] - 2023-09-22

### ✨ Features

- Added Grocy's UserFields integration (#28)

### Release

- Prepare for 0.10.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.9.1] - 2023-08-05

### Release

- Prepare for 0.9.1

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.9.0] - 2023-08-05

### ✨ Features

- Added ability to use MQTT custom port (#27)

### Release

- Prepare for 0.9.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.8.1] - 2023-07-27

### ⚙️ Miscellaneous

- Update services definition to fix hassfest error

### Release

- Prepare for 0.8.1

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.8.0] - 2023-06-22

### ✨ Features

- Allow users to change the 'Default quantity unit purchase' and use the 'Factor purchase to stock quantity unit (#24)'

### Release

- Prepare for 0.8.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.7.1] - 2023-06-16

### 🐛 Bug Fixes

- Fixed issue in refresh product service

### Release

- Prepare for 0.7.1

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.7.0] - 2023-06-14

### ✨ Features

- Added display and management of multiple shopping lists (#21)

### 📚 Documentation

- After this update, you might have products in double, just hit refresh service and they should disappear. Don't forget to read the changelog and README for other breaking changes.

### Release

- Prepare for 0.7.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.6.1] - 2023-05-29

### 🐛 Bug Fixes

- Avoid problems with non-Latin alphabets (#20)

### 📚 Documentation

- After this update, you might have products in double, just hit refresh service and they should disappear

### Release

- Prepare for 0.6.1

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.6.0] - 2023-05-25

### ✨ Features

- Added qty_in_stock attribute (#19)

### Release

- Prepare for 0.6.0

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.5.3] - 2023-04-12

### ✨ Features

- Defined more image sizes in config flow

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.5.2] - 2023-04-04

### 🐛 Bug Fixes

- Fixed issue raised in #16 with config flow

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.5.1] - 2023-04-04

### 🐛 Bug Fixes

- Fixed issue raised in #16 with config flow

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.5.0] - 2023-04-04

### ✨ Features

- Define image size in config flow (thanks @rachaelbond)
- Added Spanish translation
- Updated sensor ID by appending grocy's product ID and thus create unique sensors (PR #11)

### 📚 Documentation

- With this update, products entity_id are updated. If you see some inconsistencies, try to refresh your list several time with the provided service, and don't forget to restart your HomeAssistant.

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.4.0] - 2023-03-13

### ✨ Features

- Added a new config option to use/display product images

### 🚜 Refactor

- Improved API calls to Grocy

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.7] - 2023-02-23

### ⚙️ Miscellaneous

- Fix manifest file

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.6] - 2023-01-12

### 📚 Documentation

- Update HACS URL

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.5] - 2023-01-08

### 📚 Documentation

- Updated filter condition in example

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.4] - 2022-12-29

### 🐛 Bug Fixes

- Fixed issue where main sensors state was reset to 0 after few minutes

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.3] - 2022-12-29

### 🚜 Refactor

- Refactored some code

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.2] - 2022-12-28

### 🐛 Bug Fixes

- Fixed issue with ascii encoding (issue #2)

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.1] - 2022-12-28

### 📚 Documentation

- Update documentation for Grocy's Home Assistant add-on usage

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.3.0] - 2022-12-28

### ✨ Features

- Added configuration flow. A restart is still required.

### 🐛 Bug Fixes

- Fixed issue with special German umlauts characters (#2)

### 📚 Documentation

- Update documentation for Grocy's Home Assistant add-on usage

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.2.0] - 2022-12-28

### ✨ Features

- Added product group as attribute

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.1.2] - 2022-12-27

### 🐛 Bug Fixes

- Fixed missing translation in English

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.1.1] - 2022-12-22

### 🐛 Bug Fixes

- Allow private IP instances as workaround for issue #1

### 📚 Documentation

- Update documentation about SSL verification checkbox

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.1.0] - 2022-12-20

### ✨ Features

- Added new switch to pause updates from grocy instance

### 📚 Documentation

- Update documentation

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.0.2] - 2022-11-25

### 🐛 Bug Fixes

- Remove old action file

### 📚 Documentation

- Update documentation

⚠️ The project is still under active development. Until `1.0.0`, breaking changes can be included in MINOR versions.
## [0.0.1] - 2022-11-25

### ✨ Features

- Initial release

<!-- generated by git-cliff -->
