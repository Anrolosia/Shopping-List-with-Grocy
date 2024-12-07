
<h1 align="center">Shopping List with Grocy Integration</h1>

<p align="center">
  <a href="https://github.com/Anrolosia/Shopping-List-with-Grocy">
    <img src="https://img.shields.io/github/v/release/Anrolosia/Shopping-List-with-Grocy?style=for-the-badge" alt="Release" />
  </a>
  <a href="https://github.com/Anrolosia/Shopping-List-with-Grocy">
    <img src="https://img.shields.io/github/last-commit/Anrolosia/Shopping-List-with-Grocy?style=for-the-badge" alt="Last Commit" />
  </a>
  <a href="https://github.com/hacs/integration">
    <img src="https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge" alt="HACS" />
  </a>
  <a href="https://github.com/Anrolosia">
    <img src="https://img.shields.io/badge/maintainer-%40Anrolosia-blue.svg?style=for-the-badge" alt="HACS" />
  </a>
  <a href="https://www.buymeacoffee.com/anrolosia">
    <img src="https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow?style=for-the-badge" alt="Donate Coffee" />
  </a>
</p>

<p align="center">
  Integrate and interact with your <a href="https://grocy.info/">Grocy</a> shopping list directly from your Home Assistant dashboard.
</p>

<p align="center">
  :warning: This is still an early release. It may not be stable and it may have bugs. :warning:<br />
  See the <a href="https://github.com/Anrolosia/Shopping-List-with-Grocy">Issues</a> page to report a bug or to add a feature request.
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Anrolosia/Shopping-List-with-Grocy/main/images/showcase.png" alt="Showcase Example" />
</p>

<p align="center">
  The image above was generated using <a href="https://github.com/thomasloven/lovelace-auto-entities">Auto Entities Card</a>, <a href="https://github.com/thomasloven/lovelace-card-mod">Card Mods Card</a> and <a href="https://github.com/custom-cards/button-card">Custom Button Card</a>.
</p>

---

## Requirements 💡

This integration uses MQTT with auto discovery:

- [MQTT Integration](https://www.home-assistant.io/integrations/mqtt)

## Installation 🏠

Installation is a multi-step process. Follow each of the following steps.

### 1. Add HACS Integration

This integration is available in [HACS](https://hacs.xyz/) (Home Assistant Community Store). You can click on

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=anrolosia&repository=shopping-list-with-grocy&category=integration" target="_blank"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open a repository inside the Home Assistant Community Store." /></a>

or install it manually as follows:

- In Home Assistant, go to HACS > Integrations
- Press the **Explore & Add Repositories** button
- Search for "Grocy" and choose this integration
- Press the **Install this repository in HACS** button
- Press the **Install** button

### 2. Prepare Grocy

You have to provide an `url` and an `API key` to use this integration. 

- Go to the manageapikeys page on Grocy and press the **Add** button
- Copy your Grocy main URL (``https://<url-of-your-grocy-installation>/`` and your newly generated API key

### 3. Add Home Assistant Integration

Clik on

<a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=shopping_list_with_grocy" target="_blank"><img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Open your Home Assistant instance and start setting up a new integration." /></a>

or install it manually as follows:

- In Home Assistant, go to Configuration > Integrations
- Press the **Add Integration** button
- Search for "Grocy" and click on this integration
- Follow the configuration process

Depending on the number of products you have in your Grocy instance, the sensors may take a while to be created and populated.

:warning: If you want to use Grocy's add-on from Home assistant, please configure a port/web interface in grocy addon config at the bottom, f.e. 9192
then use your HA address like this: https://192.168.1.1:9192 and uncheck the Verify SSL certificate checkbox. You SHOULD use https if your Grocy's module is configured to use SSL (even if you don't have any certificate). Use http:// if it's not checked :warning:

<img src="https://raw.githubusercontent.com/Anrolosia/Shopping-List-with-Grocy/main/images/grocy_addon_ssl.png" alt="Grocy add-on SSL" />

## Available Sensors

This integration will create as much sensors as you have products configured in your Grocy instance, but will also create 3 other sensors:

##### Product sensor

This sensor (``sensor.products_shopping_list_with_grocy``) state is the current number of products you  have in your Grocy instance.
If you checked the option during the configuration of the module to include more informations, you'll have all your products here too.

##### Shopping list sensor

This sensor (``sensor.shopping_list_shopping_list_with_grocy``) state is the current number of products you  have in your shopping list on Grocy.
If you checked the option during the configuration of the module to include more informations, you'll have all your products here too.

##### Updating sensor

This sensor (``binary_sensor.updating_shopping_list_with_grocy``) show current status of list update.

## Available Switch

##### Pause update

This switch (``switch.pause_update_shopping_list_with_grocy``) will prevent any updates from your Grocy instance to your Home Assistant.
It could be useful if you want to update several products at once or run a long script.

## Available Services

This integration provides 4 services

##### shopping_list_with_grocy.add_product

```yaml
service: shopping_list_with_grocy.add_product
data:
  product_id: sensor.shopping_list_with_grocy_<your product>
  shopping_list_id: <id of your shopping list on Grocy> # Optional, default is list 1
  note: "This is the note of the shopping list item..."
```
##### shopping_list_with_grocy.remove_product

```yaml
service: shopping_list_with_grocy.remove_product
data:
  product_id: sensor.shopping_list_with_grocy_<your product>
  shopping_list_id: <id of your shopping list on Grocy> # Optional, default is list 1
```

##### shopping_list_with_grocy.update_note

```yaml
service: shopping_list_with_grocy.update_note
data:
  product_id: sensor.shopping_list_with_grocy_<your product>
  shopping_list_id: <id of your shopping list on Grocy> # Optional, default is list 1
  note: "This is the note of the shopping list item..."
```

##### shopping_list_with_grocy.refresh_products

```yaml
service: shopping_list_with_grocy.refresh_products
data: {}
```

#### Custom products UserFields

In Grocy -> Manage master data -> Userfields, you can add custom fields on your products. You can now use that!

For example, if you want to create a custom sort, create a custom field in Grocy:
```yaml
Entity: products
Name: customsort
Caption: Custom sort
Type: Number(decimal)
Show as column in tables: checked
```

then modify your dashboard to use that sort by replacing

```yaml
sort:
  method: friendly_name
```
with
```yaml
sort:
  method: attribute
  attribute: userfields:customsort
  numeric: true
```

## Known issues / FAQ 💡

#### binary_sensor.updating_shopping_list_with_grocy is not created

There is probably an issue with your MQTT configuration, you have to create a user, MQTT no longer allows anonymous connections, please check [this link](https://github.com/Anrolosia/Shopping-List-with-Grocy/issues/29#issuecomment-1782905325)

## Card

A card for this integration is available in [HACS](https://hacs.xyz/) (Home Assistant Community Store). You can click on

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=anrolosia&repository=shopping-list-with-grocy-card" target="_blank"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open a repository inside the Home Assistant Community Store." /></a>

or on Github : [Shopping List with Grocy Card](https://github.com/Anrolosia/Shopping-List-with-Grocy-Card)

## Additional Information ℹ️

### Feature Requests and Contributions

Don't hesitate to [ask for features](https://github.com/Anrolosia/Shopping-List-with-Grocy/issues) or contribute your own [pull request](https://github.com/Anrolosia/Shopping-List-with-Grocy/pulls). ⭐
