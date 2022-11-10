
<h1 align="center">Shopping List with Grocy Integration</h1>

<p align="center">
  <a href="https://github.com/custom-components/hacs">
    <img src="https://img.shields.io/badge/HACS-Default-orange.svg" alt="HACS" />
  </a>
  <a href="https://github.com/Anrolosia/Shopping-List-with-Grocy">
    <img src="https://img.shields.io/github/v/release/Anrolosia/Shopping-List-with-Grocy" alt="Release" />
  </a>
  <a href="https://github.com/Anrolosia/Shopping-List-with-Grocy">
    <img src="https://img.shields.io/github/last-commit/Anrolosia/Shopping-List-with-Grocy" alt="Last Commit" />
  </a>
  <a href="https://www.buymeacoffee.com/anrolosia">
    <img src="https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow" alt="Donate Coffee" />
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

This integration is available in [HACS](https://hacs.xyz/) (Home Assistant Community Store). Install it as follows:

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

- In Home Assistant, go to Configuration > Integrations
- Press the **Add Integration** button
- Search for "Grocy" and click on this integration
- Follow the configuration process

Depending on the number of products you have in your Grocy instance, the sensors may take a while to be created and populated.

#### Available Sensors

This integration will create as much sensors as you have products configured in your Grocy instance, but will also create 3 other sensors:

##### Product sensor

This sensor (``sensor.products_shopping_list_with_grocy``) state is the current number of products you  have in your Grocy instance.
If you checked the option during the configuration of the module to include more informations, you'll have all your products here too.

##### Shopping list sensor

This sensor (``sensor.shopping_list_shopping_list_with_grocy``) state is the current number of products you  have in your shopping list on Grocy.
If you checked the option during the configuration of the module to include more informations, you'll have all your products here too.

##### Updating sensor

This sensor (``binary_sensor.updating_shopping_list_with_grocy``) show current status of list update.

#### Available Services

This integration provides 4 services

##### shopping_list_with_grocy.add_product

```yaml
service: shopping_list_with_grocy.add_product
data:
  product_id: sensor.shopping_list_with_grocy_<your product>
  note: "This is the note of the shopping list item..."
```
##### shopping_list_with_grocy.remove_product

```yaml
service: shopping_list_with_grocy.remove_product
data:
  product_id: sensor.shopping_list_with_grocy_<your product>
```

##### shopping_list_with_grocy.update_note

```yaml
service: shopping_list_with_grocy.update_note
data:
  product_id: sensor.shopping_list_with_grocy_<your product>
  note: "This is the note of the shopping list item..."
```

##### shopping_list_with_grocy.refresh_products

```yaml
service: shopping_list_with_grocy.refresh_products
data: {}
```

#### Example of dashboard UI

If you want to build the same example as on the screenshot above, this is an example of dashboard UI

```yaml
type: custom:bootstrap-grid-card
cards:
  - type: row
    class: justify-content-center
    cards:
      - type: custom:auto-entities
        class: col-12 col-lg-9 p-0
        card:
          type: custom:layout-card
          layout_type: grid
          layout_options:
            grid-template-columns: 20% 20% 20% 20% 20%
            mediaquery:
              '(max-width: 600px)':
                grid-template-columns: 50% 50%
              '(max-width: 800px)':
                grid-template-columns: 25% 25% 25% 25%
        filter:
          include:
            - entity_id: sensor.shopping_list_with_grocy_.*
              sort:
                method: friendly_name
              options:
                type: custom:button-card
                entity: this.entity_id
                aspect_ratio: 4/3
                show_icon: false
                show_label: true
                show_state: true
                label: |
                  [[[
                    return `(${entity.attributes.location})`
                  ]]]
                tap_action:
                  action: call-service
                  service: shopping_list_with_grocy.add_product
                  service_data:
                    product_id: this.entity_id
                double_tap_action:
                  action: call-service
                  service: shopping_list_with_grocy.remove_product
                  service_data:
                    product_id: this.entity_id
                hold_action:
                  action: call-service
                  service: shopping_list_with_grocy.remove_product
                  service_data:
                    product_id: this.entity_id
                styles:
                  label:
                    - z-index: 1
                    - font-size: small
                    - margin-top: 1vh
                  name:
                    - z-index: 1
                    - font-size: large
                    - font-weight: bold
                    - margin-bottom: 1vh
                  card:
                    - background-image: |
                        [[[
                           return 'url("data:image/jpg;base64,' + `${entity.attributes.product_image}` + '")';
                        ]]]
                    - background-repeat: no-repeat
                    - background-position: center
                    - background-size: cover
                    - border-width: |
                        [[[
                          if (entity.attributes.product_image)
                           return "0";
                          else
                           return "var(--ha-card-border-width, 1px)";
                        ]]]
                  state:
                    - background-color: green
                    - border-radius: 50%
                    - position: absolute
                    - right: 5%
                    - top: 5%
                    - height: |
                        [[[
                          if (entity.state > 0) return '20px';
                          else return '0px';
                        ]]]
                    - width: |
                        [[[
                          if (entity.state > 0) return '20px';
                          else return '0px';
                        ]]]
                    - font-size: |
                        [[[
                          if (entity.state > 0) return '14px';
                          else return '0px';
                        ]]]
                    - line-height: |
                        [[[
                          if (entity.state > 0) return '20px';
                          else return '0px';
                        ]]]
                  custom_fields:
                    gradient:
                      - display: |
                          [[[
                            if (entity.attributes.product_image)
                             return "block";
                            else
                             return "none";
                          ]]]
                      - height: |
                          [[[
                            if (entity.attributes.product_image)
                             return "100%";
                            else
                             return "0px";
                          ]]]
                      - width: |
                          [[[
                            if (entity.attributes.product_image)
                             return "100%";
                            else
                             return "0px";
                          ]]]
                      - font-size: |
                          [[[
                            if (entity.attributes.product_image)
                             return "auto";
                            else
                             return "0px";
                          ]]]
                      - line-height: |
                          [[[
                            if (entity.attributes.product_image)
                             return "auto";
                            else
                             return "0px";
                          ]]]
                custom_fields:
                  gradient: '&nbsp;'
                card_mod:
                  style: |
                    ha-card {
                      height: 100%;
                      height: -moz-available;          /* WebKit-based browsers will ignore this. */
                      height: -webkit-fill-available;  /* Mozilla-based browsers will ignore this. */
                      height: fill-available;
                    }
                    ha-card #gradient {
                      position: absolute !important;
                      top: 0%;
                      left: 0;
                      z-index: 0;
                      background-image: linear-gradient(
                        0deg,
                        hsla(0, 0%, 0%, 0.8) 0%,
                        hsla(0, 0%, 0%, 0.79) 8.3%,
                        hsla(0, 0%, 0%, 0.761) 16.3%,
                        hsla(0, 0%, 0%, 0.717) 24.1%,
                        hsla(0, 0%, 0%, 0.66) 31.7%,
                        hsla(0, 0%, 0%, 0.593) 39%,
                        hsla(0, 0%, 0%, 0.518) 46.1%,
                        hsla(0, 0%, 0%, 0.44) 53%,
                        hsla(0, 0%, 0%, 0.36) 59.7%,
                        hsla(0, 0%, 0%, 0.282) 66.1%,
                        hsla(0, 0%, 0%, 0.207) 72.3%,
                        hsla(0, 0%, 0%, 0.14) 78.3%,
                        hsla(0, 0%, 0%, 0.083) 84%,
                        hsla(0, 0%, 0%, 0.039) 89.6%,
                        hsla(0, 0%, 0%, 0.01) 94.9%,
                        hsla(0, 0%, 0%, 0) 100%
                      );
                    }
                    ha-card .ellipsis {
                      white-space: normal
                    }
          exclude: []
        sort:
          method: attribute
          attribute: location
      - type: col
        class: col-12 col-lg-3 p-0 pt-2 pb-2
        cards:
          - type: row
            cards:
              - type: custom:button-card
                entity: sensor.products_shopping_list_with_grocy
                class: col
                icon: mdi:cart-remove
                show_name: false
                tap_action:
                  action: call-service
                  service: script.grocy_clear_shopping_list
                hold_action: none
                double_tap_action: none
                confirmation:
                  text: This will clear your shopping list, are you sure?
              - type: custom:button-card
                entity: binary_sensor.updating_shopping_list_with_grocy
                class: col
                show_name: false
                tap_action:
                  action: call-service
                  service: shopping_list_with_grocy.refresh_products
                hold_action: none
                double_tap_action: none
                color: var(--primary-text-color)
                state:
                  - value: 'on'
                    styles:
                      icon:
                        - animation: rotating 1s linear infinite
          - type: custom:auto-entities
            filter:
              include:
                - entity_id: sensor.shopping_list_with_grocy_.*
                  attributes:
                    qty_in_shopping_list: '>=1'
                  not:
                    attributes:
                      note: out_of_stock
                  options:
                    type: tile
                    entity: this.entity_id
                    show_name: false
                    show_icon: true
                    aspect_ratio: 1/1
                    icon: mdi:cart-remove
                    icon_tap_action:
                      action: call-service
                      service: shopping_list_with_grocy.remove_product
                      service_data:
                        product_id: this.entity_id
                    tap_action:
                      action: call-service
                      service: shopping_list_with_grocy.update_note
                      service_data:
                        product_id: this.entity_id
                        note: out_of_stock
                    card_mod:
                      style:
                        ha-tile-info$: |
                          .info {
                            flex-direction: row !important;
                            align-items: center !important;
                            align-content: stretch;
                            flex-wrap: nowrap;
                            justify-content: flex-start;
                            height: 100%;
                            height: -moz-available;          /* WebKit-based browsers will ignore this. */
                            height: -webkit-fill-available;  /* Mozilla-based browsers will ignore this. */
                            height: fill-available;
                          }
                          .primary {
                            flex: 1 1 auto;
                            align-self: auto;
                            width: auto;
                          }
                          .secondary {
                            flex: 0 1 auto;
                            align-self: auto;
                            width: auto;
                            font-size: initial !important;
                          }
                        .: |
                          ha-tile-info {
                            display: flex;
                            align-items: center;
                            height: 100%;
                            height: -moz-available;          /* WebKit-based browsers will ignore this. */
                            height: -webkit-fill-available;  /* Mozilla-based browsers will ignore this. */
                            height: fill-available;
                          }
              exclude: []
            card:
              type: vertical-stack
            card_param: cards
            sort:
              method: friendly_name
          - type: entities
            title: Out of stock
            entities:
              - type: divider
          - type: custom:auto-entities
            filter:
              include:
                - entity_id: sensor.shopping_list_with_grocy_.*
                  attributes:
                    qty_in_shopping_list: '>=1'
                    note: out_of_stock
                  options:
                    type: tile
                    entity: this.entity_id
                    show_name: false
                    show_icon: true
                    aspect_ratio: 1/1
                    icon: mdi:cart-arrow-up
                    color: disabled
                    icon_tap_action:
                      action: call-service
                      service: shopping_list_with_grocy.update_note
                      service_data:
                        product_id: this.entity_id
                        note: ''
                    tap_action:
                      action: call-service
                      service: shopping_list_with_grocy.update_note
                      service_data:
                        product_id: this.entity_id
                        note: ''
                    card_mod:
                      style:
                        ha-tile-info$: |
                          .info {
                            flex-direction: row !important;
                            align-items: center !important;
                            align-content: stretch;
                            flex-wrap: nowrap;
                            justify-content: flex-start;
                            height: 100%;
                            height: -moz-available;          /* WebKit-based browsers will ignore this. */
                            height: -webkit-fill-available;  /* Mozilla-based browsers will ignore this. */
                            height: fill-available;
                          }
                          .primary {
                            flex: 1 1 auto;
                            align-self: auto;
                            width: auto;
                          }
                          .secondary {
                            flex: 0 1 auto;
                            align-self: auto;
                            width: auto;
                            font-size: initial;
                          }
                        .: |
                          ha-tile-info {
                            display: flex;
                            align-items: center;
                            height: 100%;
                            height: -moz-available;          /* WebKit-based browsers will ignore this. */
                            height: -webkit-fill-available;  /* Mozilla-based browsers will ignore this. */
                            height: fill-available !important;
                          }
              exclude: []
            card:
              type: vertical-stack
            card_param: cards
            sort:
              method: friendly_name

```
In the code above, you can see references on some scripts, here is the configuration:

##### scripts.yaml
```yaml
grocy_clear_shopping_list:
  alias: Clear Shopping list
  sequence:
  - alias: Set a templated variable
    variables:
      in_shopping_list: '{{ states.sensor | select("search", ".shopping_list_with_grocy_.+") | selectattr("state", "gt", "0") | selectattr("attributes.note", "eq", "") | map(attribute="entity_id") | list }}'
      default_products: [
          'sensor.shopping_list_with_grocy_<product_1>',
          'sensor.shopping_list_with_grocy_<product_4>',
          # list of products you'd like to add by default
        ]
  - repeat:
      count: '{{ in_shopping_list | count }}'
      sequence:
      - variables:
          entity_id: '{{ in_shopping_list[repeat.index - 1] }}'
      - repeat:
          count: '{{ states(entity_id) }}'
          sequence:
            - service: shopping_list_with_grocy.remove_product
              data:
                product_id: '{{ entity_id }}'
  - repeat:
      count: '{{ default_products | count }}'
      sequence:
      - variables:
          entity_id: '{{ default_products[repeat.index - 1] }}'
      - service: shopping_list_with_grocy.add_product
        data:
          product_id: '{{ entity_id }}'
  mode: single
```
## Additional Information ℹ️

### Feature Requests and Contributions

Don't hesitate to [ask for features](https://github.com/Anrolosia/Shopping-List-with-Grocy/issues) or contribute your own [pull request](https://github.com/Anrolosia/Shopping-List-with-Grocy/pulls). ⭐
