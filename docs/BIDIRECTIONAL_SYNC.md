# Bidirectional Sync - User Guide

## Overview

The bidirectional sync feature enables complete synchronization between Home Assistant shopping lists and Grocy, with automatic product creation and voice command support.

## Configuration

### Enable Bidirectional Sync

1. Go to **Configuration** → **Integrations**
2. Find **Shopping List with Grocy** and click **Configure**
3. Enable **"Enable Bidirectional Sync"**
4. Restart Home Assistant

### Voice Commands Setup (Optional)

1. Go to **Configuration** → **Blueprints**
2. Click **Import Blueprint**
3. Use this URL: `https://raw.githubusercontent.com/Anrolosia/Shopping-List-with-Grocy/refs/heads/main/blueprints/grocy_voice_bidirectional_sync.yaml`
4. Create automation based on this blueprint
5. Configure your voice assistant and language

## Features

### Core Functionality

- Add products via HA lists → Automatic creation in Grocy
- Smart search (exact match, then contains)
- Case-insensitive and accent-insensitive matching
- Quantity handling with formats like "(x2)", "(x3)"
- Automatic new product creation
- Multiple match notifications
- Multilingual voice commands (EN/FR/ES)
- Test and emergency stop services
- Existing quantity incrementation

### Product Search Logic

When adding a product through Home Assistant:

1. **Exact search**: "Milk" will find exactly "Milk"
2. **Contains search**: If no exact match, searches "Milk" in "Coconut Milk"
3. **Multiple matches**: If several matches found, notification sent for user choice
4. **Auto-creation**: If no matches found, creates the product in Grocy

### Voice Commands

#### English
- "Add milk to my shopping list"
- "Put bread on the shopping list"
- "I need coffee"
- "Add cheese to shopping list 2"
- "Remove milk from my shopping list"

#### French
- "Ajoute lait à ma liste de courses"
- "Mets pain sur la liste de courses"
- "J'ai besoin de café"
- "Ajoute fromage à la liste de courses 2"
- "Supprime lait de ma liste de courses"

#### Spanish
- "Agrega leche a mi lista de compras"
- "Pon pan en la lista de compras"
- "Necesito café"
- "Agrega queso a la lista de compras 2"
- "Elimina leche de mi lista de compras"

## Available Services

### `shopping_list_with_grocy.test_bidirectional_sync`
Tests the functionality without enabling it. Verifies everything works correctly.

**Parameters:**
- `product_name` (optional): Product name to test (default: "Test Product")
- `shopping_list_id` (optional): List ID to test (default: 1)

### `shopping_list_with_grocy.emergency_stop_sync`
Emergency stop for synchronization. Use when issues occur.

**Parameters:**
- `reason` (optional): Reason for stopping

### `shopping_list_with_grocy.restart_sync`
Restarts synchronization after emergency stop.

### `shopping_list_with_grocy.choose_product`
Selects specific product when multiple matches are found.

**Parameters:**
- `choice_key` (required): Key provided in notification
- `product_id` (required): Grocy product ID to select

## Safety Features

### Protection Against Accidental Data Loss
- Data verification before each operation
- Automatic stop if no data available
- Detailed logs for traceability
- Emergency stop always available

### Error Handling
- Error notifications
- Complete logs for debugging
- API failure fallbacks

## Notifications

The system sends notifications for:
- New product created automatically
- Multiple choice required
- Emergency stop activated
- Important errors

## Troubleshooting

### Sync Not Working
1. Check that option is enabled in configuration
2. Restart Home Assistant
3. Use test service
4. Check logs

### Products Not Found
- Search is case and accent insensitive
- Try shorter product names
- Products will be created automatically if not found

### Voice Command Issues
1. Check blueprint is properly configured
2. Test manually through HA interface first
3. Verify voice assistant is properly configured

## Usage Example

1. **Voice addition**: "Add milk to my list"
2. **Search**: System searches "milk" in Grocy
3. **Match**: Finds "Whole Milk (x1)"
4. **Increment**: Updates to "Whole Milk (x2)"
5. **Sync**: Automatic update in HA

## Important Notes

- Synchronization only works when enabled
- Direct modifications in Grocy are automatically synced to HA
- Development logs will be removed in final version
- Use emergency stop if unusual behavior occurs

## Updates

This feature is in active development. Future versions will include:
- GUI for multiple choice management
- More configuration options
- Support for additional languages
- Performance improvements
