/**
 * ANSE Panel Manager
 * Dynamically manages dashboard panels based on active plugins and event types
 * 
 * Panels are created/destroyed as plugins become active/inactive
 * Each panel is responsible for rendering its specific domain
 */

class PanelManager {
    constructor(containerSelector = '#panels-container') {
        this.container = document.querySelector(containerSelector);
        this.panels = new Map();
        this.activePlugins = new Set();
        this.panelRegistry = new Map();
        this.eventListeners = new Map();
    }

    /**
     * Register a panel type
     * panelType: 'sensor', 'actuator', 'worldmodel', 'reflex', 'eventlog', etc.
     * panelClass: Class that renders the panel
     */
    registerPanel(panelType, panelClass) {
        this.panelRegistry.set(panelType, panelClass);
        console.log(`[PanelManager] Registered panel: ${panelType}`);
    }

    /**
     * Create a panel dynamically
     */
    createPanel(panelType, panelId, config = {}) {
        if (this.panels.has(panelId)) {
            console.warn(`[PanelManager] Panel ${panelId} already exists`);
            return this.panels.get(panelId);
        }

        const PanelClass = this.panelRegistry.get(panelType);
        if (!PanelClass) {
            console.error(`[PanelManager] Unknown panel type: ${panelType}`);
            return null;
        }

        try {
            const panel = new PanelClass(panelId, config);
            panel.render(this.container);
            this.panels.set(panelId, panel);
            console.log(`[PanelManager] Created panel: ${panelId} (type: ${panelType})`);
            return panel;
        } catch (e) {
            console.error(`[PanelManager] Failed to create panel ${panelId}:`, e);
            return null;
        }
    }

    /**
     * Destroy a panel
     */
    destroyPanel(panelId) {
        const panel = this.panels.get(panelId);
        if (panel) {
            panel.destroy();
            this.panels.delete(panelId);
            console.log(`[PanelManager] Destroyed panel: ${panelId}`);
        }
    }

    /**
     * Get panel by ID
     */
    getPanel(panelId) {
        return this.panels.get(panelId);
    }

    /**
     * Get all panels of a type
     */
    getPanelsByType(panelType) {
        return Array.from(this.panels.values()).filter(p => p.panelType === panelType);
    }

    /**
     * Update panel with event
     */
    updatePanel(panelId, event) {
        const panel = this.panels.get(panelId);
        if (panel) {
            panel.update(event);
        }
    }

    /**
     * Route event to appropriate panels
     */
    routeEvent(event) {
        const { type, data, timestamp } = event;

        // These must match the wire types websocket.js actually emits
        // (sensor_event / actuator_event / reflex_event / world_model_update
        // — see the header comment in websocket.js), not the short internal
        // channel names it happens to emit() them under. They used to be the
        // short names here, so this switch never matched anything and every
        // per-type panel silently never got created — only the event log
        // worked, since it's routed to unconditionally below regardless of
        // this switch's outcome.
        switch (type) {
            case 'sensor_event':
                this.routeSensorEvent(event);
                break;

            case 'actuator_event':
                this.routeActuatorEvent(event);
                break;

            case 'reflex_event':
                this.routeReflexEvent(event);
                break;

            case 'world_model_update':
                this.routeWorldModelEvent(event);
                break;

            case 'system_event':
                this.routeSystemEvent(event);
                break;

            default:
                console.warn(`[PanelManager] Unknown event type: ${type}`);
        }

        // Route to event log
        this.updatePanel('eventlog-panel', event);
    }

    /**
     * Route sensor event to relevant sensor panels
     */
    routeSensorEvent(event) {
        const { sensor_name, sensor_type, value } = event.data;

        // Create sensor panel if it doesn't exist
        const panelId = `sensor-${sensor_name}-panel`;
        if (!this.panels.has(panelId)) {
            this.createPanel('sensor', panelId, {
                sensorName: sensor_name,
                sensorType: sensor_type,
                value: value
            });
        }

        // Update sensor panel
        this.updatePanel(panelId, event);
    }

    /**
     * Route actuator event to relevant actuator panels
     */
    routeActuatorEvent(event) {
        const { actuator_name, actuator_type, state } = event.data;

        // Create actuator panel if it doesn't exist
        const panelId = `actuator-${actuator_name}-panel`;
        if (!this.panels.has(panelId)) {
            this.createPanel('actuator', panelId, {
                actuatorName: actuator_name,
                actuatorType: actuator_type,
                state: state
            });
        }

        // Update actuator panel
        this.updatePanel(panelId, event);
    }

    /**
     * Route reflex event
     */
    routeReflexEvent(event) {
        // Update main reflex panel
        if (!this.panels.has('reflexes-panel')) {
            this.createPanel('reflex', 'reflexes-panel', {});
        }
        this.updatePanel('reflexes-panel', event);
    }

    /**
     * Route world model update
     */
    routeWorldModelEvent(event) {
        // Update world model panel
        if (!this.panels.has('worldmodel-panel')) {
            this.createPanel('worldmodel', 'worldmodel-panel', {});
        }
        this.updatePanel('worldmodel-panel', event);
    }

    /**
     * Route system event
     */
    routeSystemEvent(event) {
        const { event_type } = event.data;

        if (event_type === 'plugin_loaded') {
            const { plugin_name, plugin_type } = event.data;
            this.activePlugins.add(plugin_name);
            console.log(`[PanelManager] Plugin loaded: ${plugin_name} (${plugin_type})`);
        } else if (event_type === 'plugin_unloaded') {
            const { plugin_name } = event.data;
            this.activePlugins.delete(plugin_name);
            console.log(`[PanelManager] Plugin unloaded: ${plugin_name}`);
        }
    }

    /**
     * Get list of active panels
     */
    getActivePanels() {
        return Array.from(this.panels.keys());
    }

    /**
     * Clear all panels
     */
    clearAllPanels() {
        this.panels.forEach(panel => panel.destroy());
        this.panels.clear();
    }

    /**
     * Get number of active panels
     */
    getPanelCount() {
        return this.panels.size;
    }
}

// Export for use in browser
window.PanelManager = PanelManager;
