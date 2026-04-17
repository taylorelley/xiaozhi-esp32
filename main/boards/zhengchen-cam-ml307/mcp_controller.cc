#include <cJSON.h>
#include <esp_log.h>

#include <cstring>

#include "application.h"
#include "board.h"
#include "config.h"
#include "mcp_server.h"
#include "sdkconfig.h"
#include "settings.h"
#include "display.h"

#define TAG "MCPController"

class MCPController {
public:
    MCPController() {
        RegisterMcpTools();
        ESP_LOGI(TAG, "Registering MCP tools");
    }

	void RegisterMcpTools() {
        auto& mcp_server = McpServer::GetInstance();
		ESP_LOGI(TAG, "Starting MCP tool registration...");

	mcp_server.AddTool(
        "self.AEC.set_mode",
        "Set the AEC conversation-interrupt mode. Use this tool whenever the user wants to switch the conversation-interrupt mode, feels the AI conversation is too easily interrupted, or feels that conversation interruption is not working.\n"
        "Parameters:\n"
        "   `mode`: conversation-interrupt mode; only accepted values are `kAecOff` (disabled) and `kAecOnDeviceSide` (enabled)\n"
        "Return value:\n"
        "   Reports status information; no confirmation needed, announce the relevant data immediately\n",
        PropertyList({
            Property("mode", kPropertyTypeString)
        }),
        [](const PropertyList& properties) -> ReturnValue {
            auto mode = properties["mode"].value<std::string>();
            auto& app = Application::GetInstance();
            vTaskDelay(pdMS_TO_TICKS(2000));
            if (mode == "kAecOff") {
                app.SetAecMode(kAecOff);
                return "{\"success\": true, \"message\": \"AEC conversation-interrupt mode disabled\"}";
            }else {
                auto& board = Board::GetInstance();
                app.SetAecMode(kAecOnDeviceSide);

                return "{\"success\": true, \"message\": \"AEC conversation-interrupt mode enabled\"}";
            }
        }
    );

    mcp_server.AddTool(
        "self.AEC.get_mode",
        "Get the AEC conversation-interrupt mode state. Use this tool whenever the user wants to obtain the conversation-interrupt mode state.\n"
        "Return value:\n"
        "   Reports status information; no confirmation needed, announce the relevant data immediately\n",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            auto& app = Application::GetInstance();
            const bool is_currently_off = (app.GetAecMode() == kAecOff);
           if (is_currently_off) {
                return "{\"success\": true, \"message\": \"AEC conversation-interrupt mode is disabled\"}";
            }else {
                return "{\"success\": true, \"message\": \"AEC conversation-interrupt mode is enabled\"}";
            }
        }
    );

    mcp_server.AddTool(
        "self.res.esp_restart",
        "Restart the device. Use this tool whenever the user wants to restart the device.\n",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            vTaskDelay(pdMS_TO_TICKS(1000));
            // Reboot the device
            esp_restart();
            return true;
        }
    );

        ESP_LOGI(TAG, "MCP tool registration complete");
    }

};

static MCPController* g_mcp_controller = nullptr;

void InitializeMCPController() {
    if (g_mcp_controller == nullptr) {
        g_mcp_controller = new MCPController();
        ESP_LOGI(TAG, "Registering MCP tools");
    }
}