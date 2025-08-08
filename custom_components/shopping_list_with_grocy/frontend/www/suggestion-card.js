import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

class GrocyShoppingSuggestions extends LitElement {
    static get properties() {
        return {
            hass: { type: Object },
            config: { type: Object },
            quantities: { type: Object },
            _loading: { type: Boolean },
            _shoppingListItems: { type: Object },
            narrow: { type: Boolean, reflect: true }
        };
    }

    constructor() {
        super();
        this.quantities = {};
        this._loading = false;
        this._shoppingListItems = {};
        this.narrow = false;
        
        this._resizeHandler = this._updateNarrowState.bind(this);
    }

    connectedCallback() {
        super.connectedCallback();
        this._localTranslations = {};
        this._translationsLoaded = false;
        this._loadLocalTranslations();
        
        window.addEventListener('resize', this._resizeHandler);
        
        this._updateNarrowState();
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        window.removeEventListener('resize', this._resizeHandler);
    }

    updated(changedProps) {
        super.updated(changedProps);
        if (changedProps.has('hass')) {
            this._updateShoppingListState();
            this._updateNarrowState();
        }
    }

    _updateNarrowState() {
        const narrow = window.innerWidth < 870 || this._isSidebarCollapsed();
        if (narrow !== this.narrow) {
            this.narrow = narrow;
            if (narrow) {
                this.setAttribute('narrow', '');
            } else {
                this.removeAttribute('narrow');
            }
        }
    }

    _isSidebarCollapsed() {
        try {
            const homeAssistant = document.querySelector('home-assistant');
            const main = homeAssistant?.shadowRoot?.querySelector('home-assistant-main');
            const drawerLayout = main?.shadowRoot?.querySelector('app-drawer-layout');
            
            if (drawerLayout) {
                        return drawerLayout.narrow || drawerLayout.hasAttribute('narrow');
            }
        } catch (e) {
                return window.innerWidth < 870;
        }
        return window.innerWidth < 870;
    }

    _updateShoppingListState() {
        if (!this.hass) return;
        const newItems = {};
        Object.entries(this.hass.states).forEach(([entityId, state]) => {
            if (entityId.startsWith('shopping_list_with_grocy.')) {
                const productId = entityId.split('.')[1];
                try {
                    newItems[productId] = parseFloat(state.state) || 0;
                } catch (e) {
                    console.warn('Invalid shopping list state:', entityId, state.state);
                }
            }
        });
        this._shoppingListItems = newItems;
    }

    _interpolate(str, vars) {
        if (!vars) return str;
        return str.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
    }

    t(path, vars) {
        const core = this.hass?.localize?.(path);
        if (core && typeof core === "string") return this._interpolate(core, vars);

        const parts = path.split(".");
        let cur = this._localTranslations;
        for (const p of parts) {
            if (cur && typeof cur === "object" && p in cur) {
            cur = cur[p];
            } else {
            return this._interpolate(path, vars);
            }
        }
        return typeof cur === "string" ? this._interpolate(cur, vars) : this._interpolate(path, vars);
    }

    async _loadLocalTranslations() {
        const langRaw = this.hass?.locale?.language || "en";
        const lang = langRaw.toLowerCase().split(/[-_]/)[0];

        const base = "/shopping_list_with_grocy";
        const candidates = [
            `${base}/translations/${langRaw}.json`,
            `${base}/translations/${lang}.json`,
            `${base}/translations/en.json`,
        ];

        for (const url of candidates) {
            try {
            const res = await fetch(url, { cache: "no-store" });
            if (!res.ok) continue;
            const json = await res.json();
            this._localTranslations = json || {};
            this._translationsLoaded = true;
                this.hass?.loadBackendTranslation?.("shopping_list_with_grocy");
            this.requestUpdate();
            return;
            } catch (e) {
                }
        }
        console.warn("⚠️ No local translations found, falling back to keys.");
    }

    static get styles() {
        return css`
            @keyframes spin {
                from {
                    transform: rotate(0deg);
                }
                to {
                    transform: rotate(360deg);
                }
            }
            .spin {
                animation: spin 1s linear infinite;
            }
            :host {
                display: block;
                height: 100%;
                background-color: var(--primary-background-color);
            }
            .view {
                height: 100%;
                display: flex;
                flex-direction: column;
            }
            .header {
                background-color: var(--app-header-background-color);
                color: var(--app-header-text-color);
                border-bottom: 1px solid var(--divider-color);
                position: sticky;
                top: 0;
                z-index: 1;
            }
            .toolbar {
                display: flex;
                align-items: center;
                height: 64px;
                padding: 0 16px;
                gap: 8px;
            }
            .toolbar ha-icon-button {
                color: var(--app-header-text-color);
                --mdc-icon-button-size: 48px;
            }
            .toolbar .menu-button {
                display: none;
            }
            /* Show hamburger menu on smaller screens or when sidebar is collapsed */
            @media (max-width: 870px) {
                .toolbar .menu-button {
                    display: block;
                }
            }
            /* Also show when sidebar is explicitly collapsed (narrow mode) */
            :host([narrow]) .toolbar .menu-button {
                display: block;
            }
            .main-title {
                flex: 1;
                font-size: 20px;
                font-weight: 500;
                margin-left: 8px;
                color: var(--app-header-text-color);
            }
            .content {
                flex: 1;
                overflow-y: auto;
                padding: 16px;
            }
            ha-card {
                background-color: var(--card-background-color);
                border-radius: 12px;
                box-shadow: var(--ha-card-box-shadow);
            }
            .suggestion-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px;
                border-bottom: 1px solid var(--divider-color);
            }
            .product-info {
                flex-grow: 1;
            }
            .product-name {
                font-weight: bold;
            }
            .product-stats {
                color: var(--secondary-text-color);
                font-size: 0.9em;
            }
            .actions {
                display: flex;
                gap: 8px;
                align-items: center;
            }
            .quantity-controls {
                display: flex;
                align-items: center;
                gap: 4px;
            }
            .quantity {
                min-width: 32px;
                text-align: center;
                font-weight: bold;
            }
            ha-icon-button {
                color: var(--primary-color);
            }
            .empty {
                padding: 16px;
                text-align: center;
                color: var(--secondary-text-color);
            }
            .suggestions {
                padding: 8px 0;
            }
            .card-actions {
                border-top: 1px solid var(--divider-color);
                padding: 8px;
                display: flex;
                justify-content: flex-end;
            }
        `;
    }
    
    async _refreshSuggestions() {
        if (this._loading) return;
        try {
            this._loading = true;
            this.requestUpdate();
            await this.hass.callService('shopping_list_with_grocy', 'suggest_grocery_list', {
                disable_notification: true
            });
            this.quantities = {};
        } catch (err) {
            console.error('Error refreshing suggestions:', err);
                console.warn('Failed to refresh suggestions:', err.message);
        } finally {
            this._loading = false;
            this.requestUpdate();
        }
    }
    
    _updateQuantity(productId, change) {
        const currentQty = this.quantities[productId] || 0;
        const newQty = Math.max(0, currentQty + change);
        this.quantities = {
            ...this.quantities,
            [productId]: newQty
        };
        this.requestUpdate();
    }

    _toggleSidebar() {
        const event = new CustomEvent('hass-toggle-menu', {
            bubbles: true,
            composed: true
        });
        this.dispatchEvent(event);
        
        if (window.parent && window.parent !== window) {
            window.parent.postMessage({ type: 'hass-toggle-menu' }, '*');
        }
    }

    render() {
        if (!this.hass) return html``;

        const suggestions = this.hass.states['sensor.grocy_shopping_suggestions']?.attributes?.suggestions || [];
        const lastUpdate = this.hass.states['sensor.grocy_shopping_suggestions']?.attributes?.last_update;
        
        let emptyMessage;
        let showAddButton = false;
        
        if (this._loading) {
                emptyMessage = this.t('shopping_list_with_grocy.ui.panel.analysis_progress');
        } else if (suggestions.length === 0) {
            if (lastUpdate) {
                        emptyMessage = this.t('shopping_list_with_grocy.ui.panel.no_matches');
            } else {
                        emptyMessage = this.t('shopping_list_with_grocy.ui.panel.no_analysis');
                showAddButton = false;
            }
        }

        return html`
            <div class="view">
                <div class="header">
                    <div class="toolbar">
                        <ha-icon-button
                            class="menu-button"
                            @click=${this._toggleSidebar}
                            .path=${"M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"}
                            label=${this.t('ui.sidebar.sidebar')}>
                        </ha-icon-button>
                        <div class="main-title">${this.t('shopping_list_with_grocy.ui.panel.title')}</div>
                        <ha-icon-button
                            @click=${this._refreshSuggestions}
                            .path=${"M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z"}
                            label=${this.t('shopping_list_with_grocy.ui.panel.refresh')}
                            ?disabled=${this._loading}
                            class=${this._loading ? 'spin' : ''}>
                        </ha-icon-button>
                    </div>
                </div>
                <div class="content">
                    <ha-card>
                        <div class="card-content">
                            ${suggestions.length === 0
                                ? html`<div class="empty">${emptyMessage}</div>`
                                : html`
                                    <div class="suggestions">
                                        ${this._getVisibleSuggestions(suggestions)
                                            .map(suggestion => this._renderSuggestion(suggestion))}
                                    </div>
                                `
                            }
                        </div>
                        ${this._hasProductsToAdd(suggestions) && suggestions.length > 0
                            ? html`
                                <div class="card-actions">
                                    <mwc-button 
                                        @click=${() => this._addAllToList(suggestions)}
                                        ?disabled=${this._loading}>
                                        ${this.t('shopping_list_with_grocy.ui.panel.add_all_count', { count: this._getSelectedCount(suggestions) })}
                                    </mwc-button>
                                </div>`
                            : ''}
                    </ha-card>
                </div>
            </div>
        `;
    }

    _renderSuggestion(suggestion) {
        const quantity = this.quantities[suggestion.id] || 0;
        return html`
            <div class="suggestion-item">
                <div class="product-info">
                    <div class="product-name">${suggestion.name}</div>
                    <div class="product-stats">
                        ${this.t('shopping_list_with_grocy.ui.panel.stats.score', { score: suggestion.score.toFixed(2) })}
                    </div>
                </div>
                <div class="actions">
                    <div class="quantity-controls">
                        <ha-icon-button
                            @click=${() => this._updateQuantity(suggestion.id, -1)}
                            .path=${"M19,13H5V11H19V13Z"}
                            label=${this.t('shopping_list_with_grocy.ui.panel.quantity.decrease')}
                            ?disabled=${quantity === 0}>
                        </ha-icon-button>
                        <span class="quantity">${quantity}</span>
                        <ha-icon-button
                            @click=${() => this._updateQuantity(suggestion.id, 1)}
                            .path=${"M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z"}
                            label=${this.t('shopping_list_with_grocy.ui.panel.quantity.increase')}>
                        </ha-icon-button>
                    </div>
                    <ha-icon-button
                        @click=${() => this._addToList(suggestion)}
                        .path=${suggestion._adding 
                            ? "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z"
                            : quantity > 0 
                                ? "M9,20.42L2.79,14.21L5.62,11.38L9,14.77L18.88,4.88L21.71,7.71L9,20.42Z" 
                                : "M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12A10,10 0 0,1 12,2M12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4M12,6A6,6 0 0,1 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6M12,8A4,4 0 0,0 8,12A4,4 0 0,0 12,16A4,4 0 0,0 16,12A4,4 0 0,0 12,8Z"}
                        label=${quantity > 0 
                            ? this.t('shopping_list_with_grocy.ui.panel.quantity.add')
                            : this.t('shopping_list_with_grocy.ui.panel.quantity.select')}
                        ?disabled=${quantity === 0 || this._loading}
                        class=${suggestion._adding ? 'spin' : ''}>
                    </mwc-icon-button>
                </div>
            </div>
        `;
    }

    _getVisibleSuggestions(suggestions) {
        return suggestions.filter(suggestion => {
            const currentQuantity = this._shoppingListItems[suggestion.id] || 0;
            return currentQuantity === 0;
        });
    }

    _hasProductsToAdd(suggestions) {
        return this._getVisibleSuggestions(suggestions)
            .some(s => (this.quantities[s.id] || 0) > 0);
    }

    _getSelectedCount(suggestions) {
        return this._getVisibleSuggestions(suggestions)
            .filter(s => (this.quantities[s.id] || 0) > 0).length;
    }

    async _addAllToList(suggestions) {
        if (this._loading) return;
        
        const productsToAdd = this._getVisibleSuggestions(suggestions)
            .filter(s => (this.quantities[s.id] || 0) > 0);
        if (productsToAdd.length === 0) return;

        try {
            this._loading = true;
            this.requestUpdate();

            // Keep track of added product IDs
            const addedProductIds = [];
            
            for (const suggestion of productsToAdd) {
                const quantity = this.quantities[suggestion.id] || 0;
                await this.hass.callService('shopping_list_with_grocy', 'add_product', {
                    product_id: suggestion.id,
                    quantity: quantity,
                    disable_notification: true
                });
                addedProductIds.push(suggestion.id);
            }

            // Clear quantities for added products and update shopping list state
            const newQuantities = { ...this.quantities };
            addedProductIds.forEach(id => {
                delete newQuantities[id];
                // Update the shopping list state to reflect the added product
                this._shoppingListItems[id] = (this._shoppingListItems[id] || 0) + (this.quantities[id] || 0);
            });
            this.quantities = newQuantities;
            
            // Force an update of the shopping list state
            this._updateShoppingListState();
            
            // Schedule a delayed refresh to ensure entities are updated
            setTimeout(() => {
                this._updateShoppingListState();
                this.requestUpdate();
            }, 1000);
            
        } catch (err) {
            console.error('Error adding products to list:', err);
            console.warn('Failed to add products:', err.message);
        } finally {
            this._loading = false;
            this.requestUpdate();
        }
    }

    async _addToList(suggestion) {
        if (this._loading) return;
        const quantity = this.quantities[suggestion.id] || 0;
        if (quantity <= 0) return;

        try {
            this._loading = true;
            suggestion._adding = true;
            this.requestUpdate();

            await this.hass.callService('shopping_list_with_grocy', 'add_product', {
                product_id: suggestion.id,
                quantity: quantity,
                disable_notification: true
            });

            // Clear the quantity for this product and update shopping list state
            this.quantities = {
                ...this.quantities,
                [suggestion.id]: 0
            };
            
            // Update the shopping list state to reflect the added product
            this._shoppingListItems[suggestion.id] = (this._shoppingListItems[suggestion.id] || 0) + quantity;
            
            // Force an update of the shopping list state
            this._updateShoppingListState();
            
            // Schedule a delayed refresh to ensure entities are updated
            setTimeout(() => {
                this._updateShoppingListState();
                this.requestUpdate();
            }, 1000);
            
        } catch (err) {
            console.error('Error adding product to list:', err);
            console.warn('Failed to add product:', suggestion.name, err.message);
        } finally {
            suggestion._adding = false;
            this._loading = false;
            this.requestUpdate();
        }
    }
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "grocy-shopping-suggestions",
  name: "Grocy Shopping Suggestions",
  preview: false,
});

customElements.define("grocy-shopping-suggestions", GrocyShoppingSuggestions);



