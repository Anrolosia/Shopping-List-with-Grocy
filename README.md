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

### 🎯 **New Feature: AI-Powered Shopping Suggestions**

The integration now includes intelligent shopping suggestions powered by statistical analysis:

- **Smart Predictions:** Analyzes your purchase history to suggest products you're likely to need
- **Multi-Factor Analysis:** Considers consumption patterns, purchase frequency, and seasonal trends
- **Auto-Reset:** Suggestions automatically refresh every hour to stay current
- **Responsive Frontend:** Beautiful, mobile-friendly interface with multi-language support
- **Customizable Algorithm:** Advanced settings to fine-tune the prediction engine

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

### **Shopping Suggestions Sensor** *(New!)*
- **ID:** `sensor.grocy_shopping_suggestions`
- **Purpose:** Provides AI-powered shopping suggestions based on your purchase history
- **Features:**
  - **Statistical Analysis Engine:** Analyzes consumption patterns, purchase frequency, and seasonal trends
  - **Smart Predictions:** Suggests products you're likely to need based on historical data
  - **Auto-Reset:** Suggestions automatically reset after 1 hour to maintain freshness
  - **Manual Control:** Use the reset service to clear suggestions manually
  - **Intelligent State Detection:** Shows "Analysis in progress..." when generating suggestions, "No analysis available" when no data exists

**Attributes:**
- `suggestions`: List of suggested products with confidence scores
- `last_update`: Timestamp of when suggestions were last generated
- `state`: Number of current suggestions available

**Frontend Panel:**
Access the shopping suggestions through the dedicated frontend panel with:
- Responsive design that adapts to mobile and desktop
- Multi-language support (English, French, Spanish)
- Real-time suggestion status updates
- Easy-to-use interface for viewing and managing suggestions

---

## Services 🔧

### 🆕 **Shopping Suggestions Services**

#### Generate Shopping Suggestions
```yaml
service: shopping_list_with_grocy.suggest_grocery_list
data: {}
```
Analyzes your purchase history and generates personalized shopping suggestions based on:
- **Consumption patterns** - How quickly you use products
- **Purchase frequency** - How often you buy specific items  
- **Seasonal trends** - Time-based purchasing patterns

#### Reset Shopping Suggestions
```yaml
service: shopping_list_with_grocy.reset_suggestions
data: {}
```
Manually clears all current suggestions. Useful for:
- Starting fresh analysis
- Clearing outdated suggestions
- Testing the suggestion system

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

## ⚙️ **Advanced Configuration**

### Shopping Suggestions Algorithm Tuning

The shopping suggestions feature includes advanced configuration options for fine-tuning the prediction algorithm. Access these through the integration configuration page:

> ⚠️ **Warning:** These settings control the core algorithm. Incorrect values may break the suggestions feature. We recommend leaving defaults unchanged unless you fully understand the algorithm.

**Algorithm Weights** (must sum to 1.0):
- **Consumption Weight** (default: 0.4) - How much consumption rate affects suggestions
- **Frequency Weight** (default: 0.5) - How much purchase frequency affects suggestions  
- **Seasonal Weight** (default: 0.1) - How much seasonal patterns affect suggestions

**Threshold Settings:**
- **Score Threshold** (default: 0.3) - Minimum confidence score for suggestions (0.0-1.0)

**Example Advanced Configuration:**
```yaml
# For users who prefer frequency-based suggestions
consumption_weight: 0.3
frequency_weight: 0.5
seasonal_weight: 0.2
score_threshold: 0.65

# For seasonal shoppers
consumption_weight: 0.3
frequency_weight: 0.3
seasonal_weight: 0.4
score_threshold: 0.55
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

### Shopping Suggestions

**Q: Why am I seeing "Analysis in progress..." for a long time?**
A: The analysis requires sufficient purchase history data. Ensure you have several months of purchase data in Grocy for accurate predictions.

**Q: My suggestions seem inaccurate. How can I improve them?**
A: Try adjusting the algorithm weights in the advanced configuration. Increase the consumption weight if you want more consumption-based suggestions, or increase frequency weight for frequency-based predictions.

**Q: How often do suggestions update?**
A: Suggestions automatically reset after 1 hour to ensure freshness. You can also manually reset them using the reset service.

**Q: Can I disable the auto-reset feature?**
A: The auto-reset is built-in for optimal user experience, but you can manually generate new suggestions at any time using the suggest service.

**Q: The frontend panel shows "No analysis available"**
A: This appears when no suggestions have been generated yet or after a reset. Run the `suggest_grocery_list` service to generate new suggestions.

### General Troubleshooting

**Q: Integration not loading?**
A: Ensure your Grocy URL and API key are correct. Check the Home Assistant logs for detailed error messages.

**Q: To-Do lists not syncing?**
A: Verify that your Grocy shopping lists are accessible via the API and that the integration has proper permissions.

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