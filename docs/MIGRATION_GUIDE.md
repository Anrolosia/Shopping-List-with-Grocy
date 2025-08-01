# Migration Guide - Bidirectional Sync

## Enabling Bidirectional Sync for Existing Users

If you're already using Shopping List with Grocy, here's how to enable the new bidirectional synchronization feature:

### Step 1: Update Integration
1. Restart Home Assistant to load the new version
2. Go to **Configuration** → **Integrations**
3. Find **Shopping List with Grocy**

### Step 2: Enable Bidirectional Sync
1. Click **Configure** on your integration
2. Enable **"Enable Bidirectional Sync"**
3. Click **Save**
4. Restart Home Assistant

### Step 3: Test Functionality
1. Use service `shopping_list_with_grocy.test_bidirectional_sync`
2. Check logs to confirm everything works
3. Test by adding a product via HA list

### Step 4: Voice Commands Setup (Optional)
1. Go to **Configuration** → **Blueprints**
2. Click **Import Blueprint**
3. Add file: `blueprints/grocy_voice_bidirectional_sync.yaml`
4. Create automation based on this blueprint

## Important Considerations

### Recommended Backup
Before enabling bidirectional sync:
1. Backup your Grocy database
2. Note your current shopping lists

### First Use
- Start by testing with a few products
- Use test service before fully activating
- Keep emergency stop service ready

### Expected Behavior
- Grocy changes will appear in HA (as before)
- **NEW**: HA additions will create/update Grocy
- **NEW**: Non-existing products will be created automatically

## Safety Services

### Risk-Free Testing
```yaml
service: shopping_list_with_grocy.test_bidirectional_sync
data:
  product_name: "Test Product"
  shopping_list_id: 1
```

### Emergency Stop
```yaml
service: shopping_list_with_grocy.emergency_stop_sync
data:
  reason: "Testing or issue detected"
```

### Restart
```yaml
service: shopping_list_with_grocy.restart_sync
```

## Troubleshooting

### Sync Not Working
1. Check that option is enabled
2. Restart Home Assistant
3. Use test service
4. Check logs: **Configuration** → **Logs**

### Products Not Found
- This is normal! They will be created automatically
- Check in Grocy that they appear with correct parameters

### In Case of Issues
1. Immediately use `emergency_stop_sync`
2. Check your Grocy data
3. Review detailed logs
4. Report issue on GitHub

## Usage Example

### Manual Test
1. Go to HA list: `todo.shopping_list_with_grocy_list_1`
2. Add product: "Test Product"
3. Check it appears in Grocy
4. Modify quantity in Grocy
5. Check update in HA

### Voice Test (after blueprint configuration)
- Say: "Add milk to my shopping list"
- Check in both Grocy and HA

## New Capabilities

With this update, you can now:
- Use voice commands to manage shopping
- Add products directly in HA
- Let the system automatically create new products
- Benefit from intelligent search
- Use multiple shopping lists

Take advantage of this new functionality.
