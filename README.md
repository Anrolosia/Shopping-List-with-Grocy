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

## Overview 🛒

Easily integrate and manage your [Grocy](https://grocy.info/) shopping list within your Home Assistant dashboard. This integration seamlessly syncs with Home Assistant's native To-Do lists, enabling you to mark items as done and remove completed entries effortlessly.

> ⚠️ **Early Release Notice:** This integration is still under development. Expect possible bugs and instability. Please report any issues or request features [here](https://github.com/Anrolosia/Shopping-List-with-Grocy/issues).

---

## Installation 🏠

### 1. Install via HACS

This integration is available in [HACS](https://hacs.xyz/). You can install it by clicking:

[![HACS Repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anrolosia&repository=shopping-list-with-grocy&category=integration)

Or manually:

1. Navigate to **HACS > Integrations** in Home Assistant.
2. Click **Explore & Add Repositories**.
3. Search for **Grocy** and select this integration.
4. Click **Install this repository in HACS**.
5. Press **Install**.

### 2. Configure Grocy

- Obtain your `URL` and `API key` from Grocy:
  - Navigate to "Manage API Keys" in Grocy.
  - Click **Add** to generate a new API key.
  - Copy your Grocy URL (`https://<your-grocy-url>/`) and API key.

### 3. Add Integration in Home Assistant

Click below to start the configuration:

[![Config Flow Start](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=shopping_list_with_grocy)

Or manually:

1. Go to **Configuration > Integrations** in Home Assistant.
2. Click **Add Integration**.
3. Search for **Grocy** and select this integration.
4. Follow the setup instructions.

> ⚠️ **Important:** If using Grocy as a Home Assistant add-on, ensure you configure a port (e.g., `9192`). Use `https://<HA-IP>:9192` with SSL enabled, or `http://<HA-IP>:9192` if SSL is disabled.

---

## Features & Sensors 📊

This integration provides the following sensors:

### Product Sensor
- **ID:** `sensor.products_shopping_list_with_grocy`
- Displays the total number of products in Grocy.
- Can include product details if enabled during setup.

### Shopping List Sensor
- **ID:** `sensor.shopping_list_shopping_list_with_grocy`
- Shows the number of items in your Grocy shopping list.
- Can include product details if enabled.

### Updating Sensor
- **ID:** `binary_sensor.updating_shopping_list_with_grocy`
- Indicates if the list is currently being updated.

### Pause Update Switch
- **ID:** `switch.pause_update_shopping_list_with_grocy`
- Temporarily pauses synchronization between Grocy and Home Assistant.

---

## Services 🔧

### Add Product to Shopping List
```yaml
service: shopping_list_with_grocy.add_product
data:
  product_id: sensor.shopping_list_with_grocy_<your_product>
  shopping_list_id: <shopping_list_id> # Optional, default is list 1
  note: "Optional note..."
```

### Remove Product from Shopping List
```yaml
service: shopping_list_with_grocy.remove_product
data:
  product_id: sensor.shopping_list_with_grocy_<your_product>
  shopping_list_id: <shopping_list_id> # Optional, default is list 1
```

### Update Product Note
```yaml
service: shopping_list_with_grocy.update_note
data:
  product_id: sensor.shopping_list_with_grocy_<your_product>
  shopping_list_id: <shopping_list_id> # Optional, default is list 1
  note: "New note..."
```

### Refresh Product List
```yaml
service: shopping_list_with_grocy.refresh_products
data: {}
```

---

## Custom Product UserFields 📝

You can add custom fields to your products in Grocy and use them in Home Assistant. Example: Create a **Custom Sort** field in Grocy:

```yaml
Entity: products
Name: customsort
Caption: Custom Sort
Type: Number(decimal)
Show as column in tables: checked
```

Then modify your dashboard to sort using this field:

```yaml
sort:
  method: attribute
  attribute: userfields:customsort
  numeric: true
```

---

## Troubleshooting & FAQ ❓

---

## Additional Resources 📖

### Shopping List Card

A Lovelace card is available in HACS:

[![HACS Repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anrolosia&repository=shopping-list-with-grocy-card)

Or check it out on GitHub: [Shopping List with Grocy Card](https://github.com/Anrolosia/Shopping-List-with-Grocy-Card)

### Contribute & Support 💖

- Request new features or report issues [here](https://github.com/Anrolosia/Shopping-List-with-Grocy/issues).
- Contribute via pull requests [here](https://github.com/Anrolosia/Shopping-List-with-Grocy/pulls).
- If you find this project useful, consider [buying me a coffee](https://www.buymeacoffee.com/anrolosia) ☕!