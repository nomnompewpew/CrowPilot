# API Endpoint Matrix

Generated from live OpenAPI: `http://127.0.0.1:8787/openapi.json`

- Generated: `2026-04-20 20:55:36 UTC`
- API title: `CrowPilot API`
- API version: `0.1.0`
- Endpoint count: `148`

## Compact Matrix

| Tag | Method | Path | Access | Operation ID | Summary |
|---|---|---|---|---|---|
| auth | POST | /api/auth/change-password | public | auth_change_password_api_auth_change_password_post | Auth Change Password |
| auth | POST | /api/auth/login | public | auth_login_api_auth_login_post | Auth Login |
| auth | POST | /api/auth/logout | public | auth_logout_api_auth_logout_post | Auth Logout |
| auth | GET | /api/auth/me | public | auth_me_api_auth_me_get | Auth Me |
| chat | POST | /api/chat/stream | auth-required | chat_stream_api_chat_stream_post | Chat Stream |
| chat | POST | /api/chat/stream/approve/{token} | auth-required | approve_redaction_api_chat_stream_approve__token__post | Approve Redaction |
| chat | POST | /api/chat/stream/reject/{token} | auth-required | reject_redaction_api_chat_stream_reject__token__post | Reject Redaction |
| conversations | GET | /api/conversations | auth-required | list_conversations_api_conversations_get | List Conversations |
| conversations | POST | /api/conversations | auth-required | create_conversation_api_conversations_post | Create Conversation |
| conversations | GET | /api/conversations/sidebar | auth-required | conversation_sidebar_api_conversations_sidebar_get | Conversation Sidebar |
| conversations | DELETE | /api/conversations/{conversation_id} | auth-required | delete_conversation_api_conversations__conversation_id__delete | Delete Conversation |
| conversations | GET | /api/conversations/{conversation_id} | auth-required | get_conversation_api_conversations__conversation_id__get | Get Conversation |
| conversations | PATCH | /api/conversations/{conversation_id} | auth-required | update_conversation_api_conversations__conversation_id__patch | Update Conversation |
| conversations | GET | /api/conversations/{conversation_id}/archive-chunks | auth-required | get_conversation_archive_chunks_api_conversations__conversation_id__archive_chunks_get | Get Conversation Archive Chunks |
| conversations | GET | /api/conversations/{conversation_id}/messages | auth-required | get_messages_api_conversations__conversation_id__messages_get | Get Messages |
| copilot-history | POST | /api/copilot-history/harvest | auth-required | trigger_harvest_api_copilot_history_harvest_post | Trigger Harvest |
| copilot-history | POST | /api/copilot-history/scan | auth-required | trigger_scan_api_copilot_history_scan_post | Trigger Scan |
| copilot-history | GET | /api/copilot-history/search | auth-required | semantic_search_api_copilot_history_search_get | Semantic Search |
| copilot-history | GET | /api/copilot-history/sessions | auth-required | list_sessions_api_copilot_history_sessions_get | List Sessions |
| copilot-history | DELETE | /api/copilot-history/sessions/{session_id} | auth-required | delete_session_api_copilot_history_sessions__session_id__delete | Delete Session |
| copilot-history | GET | /api/copilot-history/sessions/{session_id} | auth-required | get_session_api_copilot_history_sessions__session_id__get | Get Session |
| copilot-history | PATCH | /api/copilot-history/sessions/{session_id} | auth-required | patch_session_api_copilot_history_sessions__session_id__patch | Patch Session |
| credentials | GET | /api/credentials | auth-required | list_credentials_api_credentials_get | List Credentials |
| credentials | POST | /api/credentials | auth-required | create_credential_api_credentials_post | Create Credential |
| credentials | GET | /api/credentials/connectors | auth-required | list_credential_connectors_api_credentials_connectors_get | List Credential Connectors |
| credentials | POST | /api/credentials/connectors/launch | auth-required | launch_credential_connector_api_credentials_connectors_launch_post | Launch Credential Connector |
| credentials | POST | /api/credentials/import-env | auth-required | import_credentials_from_env_api_credentials_import_env_post | Import Credentials From Env |
| credentials | DELETE | /api/credentials/{credential_id} | auth-required | delete_credential_api_credentials__credential_id__delete | Delete Credential |
| credentials | PATCH | /api/credentials/{credential_id} | auth-required | update_credential_api_credentials__credential_id__patch | Update Credential |
| db_connections | GET | /api/db-connections | auth-required | list_db_connections_api_db_connections_get | List Db Connections |
| db_connections | POST | /api/db-connections | auth-required | create_db_connection_api_db_connections_post | Create Db Connection |
| db_connections | DELETE | /api/db-connections/{conn_id} | auth-required | delete_db_connection_api_db_connections__conn_id__delete | Delete Db Connection |
| db_connections | PATCH | /api/db-connections/{conn_id} | auth-required | update_db_connection_api_db_connections__conn_id__patch | Update Db Connection |
| db_connections | POST | /api/db-connections/{conn_id}/introspect | auth-required | introspect_db_schema_api_db_connections__conn_id__introspect_post | Introspect Db Schema |
| db_connections | POST | /api/db-connections/{conn_id}/query | auth-required | run_db_query_api_db_connections__conn_id__query_post | Run Db Query |
| db_connections | POST | /api/db-connections/{conn_id}/test | auth-required | test_db_connection_api_db_connections__conn_id__test_post | Test Db Connection |
| integrations | GET | /api/integrations | auth-required | list_integrations_api_integrations_get | List Integrations |
| integrations | POST | /api/integrations | auth-required | create_integration_api_integrations_post | Create Integration |
| integrations | GET | /api/integrations/oauth-templates | auth-required | integration_oauth_templates_api_integrations_oauth_templates_get | Integration Oauth Templates |
| integrations | DELETE | /api/integrations/{integration_id} | auth-required | delete_integration_api_integrations__integration_id__delete | Delete Integration |
| integrations | PATCH | /api/integrations/{integration_id} | auth-required | update_integration_api_integrations__integration_id__patch | Update Integration |
| integrations | POST | /api/integrations/{integration_id}/sync-models | auth-required | sync_integration_models_api_integrations__integration_id__sync_models_post | Sync Integration Models |
| knowledge | GET | /api/notes | auth-required | list_notes_api_notes_get | List Notes |
| knowledge | POST | /api/notes | auth-required | add_note_api_notes_post | Add Note |
| knowledge | POST | /api/notes/fetch-url | auth-required | fetch_url_to_note_api_notes_fetch_url_post | Fetch Url To Note |
| knowledge | POST | /api/notes/search | auth-required | search_notes_api_notes_search_post | Search Notes |
| knowledge | DELETE | /api/notes/{note_id} | auth-required | delete_note_api_notes__note_id__delete | Delete Note |
| lan | GET | /api/lan/devices | auth-required | list_devices_api_lan_devices_get | List Devices |
| lan | POST | /api/lan/devices | auth-required | add_device_api_lan_devices_post | Add Device |
| lan | DELETE | /api/lan/devices/{device_id} | auth-required | delete_device_api_lan_devices__device_id__delete | Delete Device |
| lan | PATCH | /api/lan/devices/{device_id} | auth-required | update_device_api_lan_devices__device_id__patch | Update Device |
| lan | GET | /api/lan/devices/{device_id}/copilot | auth-required | device_copilot_api_lan_devices__device_id__copilot_get | Device Copilot |
| lan | POST | /api/lan/devices/{device_id}/copilot/harvest | auth-required | harvest_device_copilot_api_lan_devices__device_id__copilot_harvest_post | Harvest Device Copilot |
| lan | GET | /api/lan/devices/{device_id}/extensions | auth-required | device_extensions_api_lan_devices__device_id__extensions_get | Device Extensions |
| lan | GET | /api/lan/devices/{device_id}/info | auth-required | device_info_api_lan_devices__device_id__info_get | Device Info |
| lan | GET | /api/lan/devices/{device_id}/ls | auth-required | device_ls_api_lan_devices__device_id__ls_get | Device Ls |
| lan | POST | /api/lan/devices/{device_id}/ping | auth-required | ping_device_api_lan_devices__device_id__ping_post | Ping Device |
| lan | POST | /api/lan/scan | auth-required | scan_lan_api_lan_scan_post | Scan Lan |
| lan | GET | /api/lan/scan/history | auth-required | scan_history_api_lan_scan_history_get | Scan History |
| mcp | GET | /api/mcp/catalog | auth-required | mcp_catalog_api_mcp_catalog_get | Mcp Catalog |
| mcp | POST | /api/mcp/connect | auth-required | mcp_connect_api_mcp_connect_post | Mcp Connect |
| mcp | POST | /api/mcp/onboard | auth-required | mcp_onboard_api_mcp_onboard_post | Mcp Onboard |
| mcp | GET | /api/mcp/servers | auth-required | list_mcp_servers_api_mcp_servers_get | List Mcp Servers |
| mcp | POST | /api/mcp/servers | auth-required | create_mcp_server_api_mcp_servers_post | Create Mcp Server |
| mcp | DELETE | /api/mcp/servers/{server_id} | auth-required | delete_mcp_server_api_mcp_servers__server_id__delete | Delete Mcp Server |
| mcp | PATCH | /api/mcp/servers/{server_id} | auth-required | update_mcp_server_api_mcp_servers__server_id__patch | Update Mcp Server |
| mcp | POST | /api/mcp/servers/{server_id}/check | auth-required | check_mcp_server_api_mcp_servers__server_id__check_post | Check Mcp Server |
| mcp | GET | /api/mcp/vscode-config | auth-required | mcp_vscode_config_api_mcp_vscode_config_get | Mcp Vscode Config |
| mcp | GET | /mcp | public | mcp_relay_sse_mcp_get | Mcp Relay Sse |
| mcp | POST | /mcp | public | mcp_relay_mcp_post | Mcp Relay |
| network_routers | GET | /api/routers | auth-required | list_routers_api_routers_get | List Routers |
| network_routers | POST | /api/routers | auth-required | add_router_api_routers_post | Add Router |
| network_routers | DELETE | /api/routers/{router_id} | auth-required | delete_router_api_routers__router_id__delete | Delete Router |
| network_routers | PATCH | /api/routers/{router_id} | auth-required | update_router_api_routers__router_id__patch | Update Router |
| network_routers | GET | /api/routers/{router_id}/opnsense/arp | auth-required | opnsense_arp_api_routers__router_id__opnsense_arp_get | Opnsense Arp |
| network_routers | GET | /api/routers/{router_id}/opnsense/firewall | auth-required | opnsense_firewall_rules_api_routers__router_id__opnsense_firewall_get | Opnsense Firewall Rules |
| network_routers | POST | /api/routers/{router_id}/opnsense/firewall/apply | auth-required | opnsense_apply_firewall_api_routers__router_id__opnsense_firewall_apply_post | Opnsense Apply Firewall |
| network_routers | GET | /api/routers/{router_id}/opnsense/firmware | auth-required | opnsense_firmware_api_routers__router_id__opnsense_firmware_get | Opnsense Firmware |
| network_routers | GET | /api/routers/{router_id}/opnsense/interfaces | auth-required | opnsense_interfaces_api_routers__router_id__opnsense_interfaces_get | Opnsense Interfaces |
| network_routers | GET | /api/routers/{router_id}/opnsense/leases | auth-required | opnsense_leases_api_routers__router_id__opnsense_leases_get | Opnsense Leases |
| network_routers | POST | /api/routers/{router_id}/opnsense/raw | auth-required | opnsense_raw_api_routers__router_id__opnsense_raw_post | Opnsense Raw |
| network_routers | GET | /api/routers/{router_id}/opnsense/services | auth-required | opnsense_services_api_routers__router_id__opnsense_services_get | Opnsense Services |
| network_routers | GET | /api/routers/{router_id}/pfsense/arp | auth-required | pfsense_arp_api_routers__router_id__pfsense_arp_get | Pfsense Arp |
| network_routers | POST | /api/routers/{router_id}/pfsense/exec | auth-required | pfsense_exec_api_routers__router_id__pfsense_exec_post | Pfsense Exec |
| network_routers | GET | /api/routers/{router_id}/pfsense/firewall | auth-required | pfsense_firewall_api_routers__router_id__pfsense_firewall_get | Pfsense Firewall |
| network_routers | GET | /api/routers/{router_id}/pfsense/interfaces | auth-required | pfsense_interfaces_api_routers__router_id__pfsense_interfaces_get | Pfsense Interfaces |
| network_routers | POST | /api/routers/{router_id}/ping | auth-required | ping_router_api_routers__router_id__ping_post | Ping Router |
| network_routers | GET | /api/routers/{router_id}/snapshots | auth-required | list_snapshots_api_routers__router_id__snapshots_get | List Snapshots |
| network_routers | GET | /api/routers/{router_id}/snapshots/{snapshot_id} | auth-required | get_snapshot_api_routers__router_id__snapshots__snapshot_id__get | Get Snapshot |
| nomad | GET | /api/nomad/embed-mode | auth-required | get_embed_mode_api_nomad_embed_mode_get | Get Embed Mode |
| nomad | POST | /api/nomad/embed-mode | auth-required | set_embed_mode_api_nomad_embed_mode_post | Set Embed Mode |
| nomad | GET | /api/nomad/files | auth-required | list_zim_files_api_nomad_files_get | List Zim Files |
| nomad | POST | /api/nomad/files | auth-required | register_zim_file_api_nomad_files_post | Register Zim File |
| nomad | DELETE | /api/nomad/files/{zim_id} | auth-required | unregister_zim_file_api_nomad_files__zim_id__delete | Unregister Zim File |
| nomad | POST | /api/nomad/files/{zim_id}/reindex | auth-required | reindex_zim_file_api_nomad_files__zim_id__reindex_post | Reindex Zim File |
| projects | GET | /api/projects | auth-required | list_projects_api_projects_get | List Projects |
| projects | POST | /api/projects | auth-required | create_project_api_projects_post | Create Project |
| projects | POST | /api/projects/browse | auth-required | browse_and_import_project_api_projects_browse_post | Browse And Import Project |
| projects | GET | /api/projects/capabilities | auth-required | project_capabilities_api_projects_capabilities_get | Project Capabilities |
| projects | POST | /api/projects/discover | auth-required | discover_projects_api_projects_discover_post | Discover Projects |
| projects | POST | /api/projects/import | auth-required | import_project_api_projects_import_post | Import Project |
| projects | GET | /api/projects/{project_id} | auth-required | get_project_api_projects__project_id__get | Get Project |
| projects | GET | /api/projects/{project_id}/context-summary | auth-required | get_project_context_summary_api_projects__project_id__context_summary_get | Get Project Context Summary |
| projects | POST | /api/projects/{project_id}/copilot-cli | auth-required | run_project_copilot_cli_api_projects__project_id__copilot_cli_post | Run Project Copilot Cli |
| projects | POST | /api/projects/{project_id}/mkdir | auth-required | create_project_directory_api_projects__project_id__mkdir_post | Create Project Directory |
| projects | PATCH | /api/projects/{project_id}/preview | auth-required | update_project_preview_api_projects__project_id__preview_patch | Update Project Preview |
| projects | POST | /api/projects/{project_id}/run-command | auth-required | run_project_command_api_projects__project_id__run_command_post | Run Project Command |
| projects | GET | /api/projects/{project_id}/runtimes | auth-required | list_runtimes_api_projects__project_id__runtimes_get | List Runtimes |
| projects | GET | /api/projects/{project_id}/runtimes/{runtime_id}/logs | auth-required | get_runtime_logs_endpoint_api_projects__project_id__runtimes__runtime_id__logs_get | Get Runtime Logs Endpoint |
| projects | POST | /api/projects/{project_id}/runtimes/{runtime_id}/stop | auth-required | stop_runtime_endpoint_api_projects__project_id__runtimes__runtime_id__stop_post | Stop Runtime Endpoint |
| projects | GET | /api/projects/{project_id}/scripts | auth-required | get_project_scripts_api_projects__project_id__scripts_get | Get Project Scripts |
| projects | POST | /api/projects/{project_id}/scripts/run | auth-required | run_project_script_api_projects__project_id__scripts_run_post | Run Project Script |
| projects | GET | /api/projects/{project_id}/tree | auth-required | get_project_tree_api_projects__project_id__tree_get | Get Project Tree |
| sensitive | POST | /api/sensitive/redact-preview | auth-required | sensitive_redact_preview_api_sensitive_redact_preview_post | Sensitive Redact Preview |
| sensitive | POST | /api/sensitive/unredact | auth-required | sensitive_unredact_api_sensitive_unredact_post | Sensitive Unredact |
| skills | GET | /api/skills | auth-required | list_skills_api_skills_get | List Skills |
| skills | POST | /api/skills | auth-required | create_skill_api_skills_post | Create Skill |
| skills | DELETE | /api/skills/{skill_id} | auth-required | delete_skill_api_skills__skill_id__delete | Delete Skill |
| skills | PATCH | /api/skills/{skill_id} | auth-required | update_skill_api_skills__skill_id__patch | Update Skill |
| system | POST | /api/agent/fs/read | auth-required | agent_fs_read_api_agent_fs_read_post | Agent Fs Read |
| system | POST | /api/agent/fs/write | auth-required | agent_fs_write_api_agent_fs_write_post | Agent Fs Write |
| system | GET | /api/dashboard/summary | auth-required | dashboard_summary_api_dashboard_summary_get | Dashboard Summary |
| system | GET | /api/health | auth-required | health_api_health_get | Health |
| system | GET | /api/hub/access | auth-required | hub_access_api_hub_access_get | Hub Access |
| system | GET | /api/memory/queue-size | auth-required | memory_queue_size_api_memory_queue_size_get | Memory Queue Size |
| system | GET | /api/models | auth-required | list_models_for_provider_api_models_get | List Models For Provider |
| system | GET | /api/providers/{provider_name}/models | auth-required | list_provider_models_api_providers__provider_name__models_get | List Provider Models |
| system | GET | /api/system/help | auth-required | system_help_api_system_help_get | System Help |
| system | GET | /api/system/logs/stream | auth-required | stream_logs_api_system_logs_stream_get | Stream Logs |
| system | GET | /api/system/server-stats | auth-required | server_stats_api_system_server_stats_get | Server Stats |
| tasks | GET | /api/copilot/blueprint | auth-required | copilot_blueprint_api_copilot_blueprint_get | Copilot Blueprint |
| tasks | GET | /api/copilot/tasks | auth-required | list_copilot_tasks_api_copilot_tasks_get | List Copilot Tasks |
| tasks | POST | /api/copilot/tasks | auth-required | create_copilot_task_api_copilot_tasks_post | Create Copilot Task |
| tasks | PATCH | /api/copilot/tasks/{task_id} | auth-required | update_copilot_task_api_copilot_tasks__task_id__patch | Update Copilot Task |
| tasks | GET | /api/tasks | auth-required | list_automation_tasks_api_tasks_get | List Automation Tasks |
| tasks | POST | /api/tasks | auth-required | create_automation_task_api_tasks_post | Create Automation Task |
| tasks | DELETE | /api/tasks/{task_id} | auth-required | delete_automation_task_api_tasks__task_id__delete | Delete Automation Task |
| tasks | PATCH | /api/tasks/{task_id} | auth-required | update_automation_task_api_tasks__task_id__patch | Update Automation Task |
| tasks | POST | /api/tasks/{task_id}/run | auth-required | run_automation_task_api_tasks__task_id__run_post | Run Automation Task |
| untagged | GET | / | public | root__get | Root |
| untagged | GET | /favicon.ico | public | favicon_favicon_ico_get | Favicon |
| widgets | GET | /api/widgets | auth-required | list_widgets_api_widgets_get | List Widgets |
| widgets | POST | /api/widgets | auth-required | create_widget_api_widgets_post | Create Widget |
| widgets | DELETE | /api/widgets/{widget_id} | auth-required | delete_widget_api_widgets__widget_id__delete | Delete Widget |
| widgets | PATCH | /api/widgets/{widget_id} | auth-required | update_widget_api_widgets__widget_id__patch | Update Widget |
| wizard | POST | /api/wizard/complete | public | wizard_complete_api_wizard_complete_post | Wizard Complete |
| wizard | GET | /api/wizard/status | public | wizard_status_api_wizard_status_get | Wizard Status |
| zen | POST | /api/zen/act | auth-required | zen_action_api_zen_act_post | Zen Action |

## Access Classification

- `public`: allowed by auth middleware prefixes/exact paths
- `auth-required`: all other endpoints

Access is derived from `backend/app/middleware/auth.py` rules.
