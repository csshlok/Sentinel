// Generated from the root openapi.json by scripts/api/generate.mjs. Do not edit.
export interface paths {
    "/api/v1/actors": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Actors */
        get: operations["list_actors_api_v1_actors_get"];
        put?: never;
        /** Create Actor */
        post: operations["create_actor_api_v1_actors_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/actors/{actor_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Actor */
        get: operations["get_actor_api_v1_actors__actor_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents/adapters": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Agent Adapters */
        get: operations["list_agent_adapters_api_v1_agents_adapters_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/capabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Capabilities */
        get: operations["capabilities_api_v1_capabilities_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Changes */
        get: operations["list_changes_api_v1_changes_get"];
        put?: never;
        /** Create Change */
        post: operations["create_change_api_v1_changes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Change */
        get: operations["get_change_api_v1_changes__change_id__get"];
        put?: never;
        post?: never;
        /** Delete Change */
        delete: operations["delete_change_api_v1_changes__change_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Agent Runs */
        get: operations["list_agent_runs_api_v1_changes__change_id__agents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/agents/attach": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Attach Agent */
        post: operations["attach_agent_api_v1_changes__change_id__agents_attach_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/agents/launch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Launch Agent */
        post: operations["launch_agent_api_v1_changes__change_id__agents_launch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/agents/{run_id}/pause": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Pause Agent */
        post: operations["pause_agent_api_v1_changes__change_id__agents__run_id__pause_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/agents/{run_id}/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resume Agent */
        post: operations["resume_agent_api_v1_changes__change_id__agents__run_id__resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/agents/{run_id}/stop": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Stop Agent */
        post: operations["stop_agent_api_v1_changes__change_id__agents__run_id__stop_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/assurance/facts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Assurance Facts */
        get: operations["get_assurance_facts_api_v1_changes__change_id__assurance_facts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/assurance/plan": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Latest Assurance Plan */
        get: operations["get_latest_assurance_plan_api_v1_changes__change_id__assurance_plan_get"];
        put?: never;
        /** Plan Assurance */
        post: operations["plan_assurance_api_v1_changes__change_id__assurance_plan_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/assurance/{plan_id}/evaluation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Evaluate Assurance */
        get: operations["evaluate_assurance_api_v1_changes__change_id__assurance__plan_id__evaluation_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/assurance/{plan_id}/run": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Run Assurance */
        post: operations["run_assurance_api_v1_changes__change_id__assurance__plan_id__run_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Change */
        post: operations["cancel_change_api_v1_changes__change_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/contract": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Change Contract */
        put: operations["update_change_contract_api_v1_changes__change_id__contract_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/delegations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Delegations */
        get: operations["list_delegations_api_v1_changes__change_id__delegations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/dependencies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Dependencies */
        get: operations["get_dependencies_api_v1_changes__change_id__dependencies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/environment": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Environment */
        get: operations["get_environment_api_v1_changes__change_id__environment_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Journal Events */
        get: operations["list_journal_events_api_v1_changes__change_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Evidence */
        get: operations["get_evidence_api_v1_changes__change_id__evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/evidence/baseline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Capture Baseline */
        post: operations["capture_baseline_api_v1_changes__change_id__evidence_baseline_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/evidence/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Capture Current Evidence */
        post: operations["capture_current_evidence_api_v1_changes__change_id__evidence_current_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/fork": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Fork Change */
        post: operations["fork_change_api_v1_changes__change_id__fork_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/forks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Change Forks */
        get: operations["list_change_forks_api_v1_changes__change_id__forks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/git/checkpoints": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Git Checkpoints */
        get: operations["list_git_checkpoints_api_v1_changes__change_id__git_checkpoints_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/git/compare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Compare Git Checkpoints */
        get: operations["compare_git_checkpoints_api_v1_changes__change_id__git_compare_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/outcomes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Outcomes */
        get: operations["list_outcomes_api_v1_changes__change_id__outcomes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/outcomes/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Refresh Outcomes */
        post: operations["refresh_outcomes_api_v1_changes__change_id__outcomes_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/passport": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Latest Passport */
        get: operations["get_latest_passport_api_v1_changes__change_id__passport_get"];
        put?: never;
        /** Build Passport */
        post: operations["build_passport_api_v1_changes__change_id__passport_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/providers/github/grants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Issue Github Grant */
        post: operations["issue_github_grant_api_v1_changes__change_id__providers_github_grants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/providers/github/grants/{grant_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Github Grant */
        post: operations["revoke_github_grant_api_v1_changes__change_id__providers_github_grants__grant_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/providers/github/pulls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Pull Request */
        post: operations["create_pull_request_api_v1_changes__change_id__providers_github_pulls_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/providers/github/pulls/close": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Close Pull Request */
        post: operations["close_pull_request_api_v1_changes__change_id__providers_github_pulls_close_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/recovery": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Latest Recovery */
        get: operations["get_latest_recovery_api_v1_changes__change_id__recovery_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/recovery/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Preview Recovery */
        post: operations["preview_recovery_api_v1_changes__change_id__recovery_preview_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/recovery/{plan_id}/execute": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Execute Recovery */
        post: operations["execute_recovery_api_v1_changes__change_id__recovery__plan_id__execute_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Refresh Change */
        post: operations["refresh_change_api_v1_changes__change_id__refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/replay": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Replay */
        get: operations["get_replay_api_v1_changes__change_id__replay_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/replay/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Replay */
        get: operations["export_replay_api_v1_changes__change_id__replay_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/replay/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Verify Replay */
        get: operations["verify_replay_api_v1_changes__change_id__replay_verify_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/tools": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Tools For Change */
        get: operations["list_tools_for_change_api_v1_changes__change_id__tools_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/tools/declare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Declare Tool Manifest */
        post: operations["declare_tool_manifest_api_v1_changes__change_id__tools_declare_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/transition": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Transition Change */
        post: operations["transition_change_api_v1_changes__change_id__transition_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/changes/{change_id}/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Verify Change */
        post: operations["verify_change_api_v1_changes__change_id__verify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/delegations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Delegation */
        post: operations["create_delegation_api_v1_delegations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/delegations/{delegation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Delegation */
        get: operations["get_delegation_api_v1_delegations__delegation_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/delegations/{delegation_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Delegation */
        post: operations["revoke_delegation_api_v1_delegations__delegation_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_v1_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/providers/github/connect": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Connect Github */
        post: operations["connect_github_api_v1_providers_github_connect_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/providers/github/disconnect": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Disconnect Github */
        post: operations["disconnect_github_api_v1_providers_github_disconnect_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/providers/github/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Github Status */
        get: operations["github_status_api_v1_providers_github_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/repositories/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Validate Repository */
        post: operations["validate_repository_api_v1_repositories_validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/system/backend-identity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Backend Identity */
        get: operations["backend_identity_api_v1_system_backend_identity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tools": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Tools */
        get: operations["list_tools_api_v1_tools_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tools/{tool_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Tool */
        get: operations["get_tool_api_v1_tools__tool_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/tools/{tool_id}/trust": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide Tool Trust */
        post: operations["decide_tool_trust_api_v1_tools__tool_id__trust_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** Actor */
        Actor: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Display Name */
            display_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            kind: components["schemas"]["ActorKind"];
            /** Provenance */
            provenance?: {
                [key: string]: unknown;
            };
            /**
             * Revision
             * @default 1
             */
            revision: number;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** ActorActionRequest */
        ActorActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
        };
        /** ActorCreateRequest */
        ActorCreateRequest: {
            /** Display Name */
            display_name: string;
            kind: components["schemas"]["ActorKind"];
            /** Provenance */
            provenance?: {
                [key: string]: unknown;
            };
        };
        /**
         * ActorKind
         * @enum {string}
         */
        ActorKind: "HUMAN" | "AGENT" | "SERVICE";
        /** ActorListResponse */
        ActorListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["Actor"][];
            /** Total */
            total: number;
        };
        /** AgentAdapterInfo */
        AgentAdapterInfo: {
            /** Adapter */
            adapter: string;
            /** Credential Keys */
            credential_keys?: string[];
            /**
             * Descendant Control Available
             * @default false
             * @constant
             */
            descendant_control_available: false;
            /** Executables */
            executables: {
                [key: string]: boolean;
            };
        };
        /** AgentAdapterListResponse */
        AgentAdapterListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["AgentAdapterInfo"][];
        };
        /** AgentAttachActionRequest */
        AgentAttachActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            attach: components["schemas"]["AgentAttachRequest"];
        };
        /** AgentAttachRequest */
        AgentAttachRequest: {
            /** Adapter */
            adapter: string;
            /** Declared Started At */
            declared_started_at?: string | null;
            /** External Run Id */
            external_run_id: string;
        };
        /** AgentLaunchActionRequest */
        AgentLaunchActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            launch: components["schemas"]["AgentLaunchRequest"];
            /**
             * Output Limit Bytes
             * @default 200000
             */
            output_limit_bytes: number;
        };
        /** AgentLaunchRequest */
        AgentLaunchRequest: {
            /** Adapter */
            adapter: string;
            /** Args */
            args?: string[];
            /** Environment Keys */
            environment_keys?: string[];
            /** Executable */
            executable: string;
            /**
             * Timeout Seconds
             * @default 900
             */
            timeout_seconds: number;
        };
        /** AgentRun */
        AgentRun: {
            /** Adapter */
            adapter: string;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Completed At */
            completed_at?: string | null;
            /**
             * Descendant Control Available
             * @default false
             * @constant
             */
            descendant_control_available: false;
            /** Duration Ms */
            duration_ms?: number | null;
            /** Exit Code */
            exit_code?: number | null;
            /** External Run Id */
            external_run_id?: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Limitations */
            limitations?: string[];
            /**
             * Output Truncated
             * @default false
             */
            output_truncated: boolean;
            /** Paused At */
            paused_at?: string | null;
            /** Resumed At */
            resumed_at?: string | null;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            status: components["schemas"]["AgentRunStatus"];
            /**
             * Stderr
             * @default
             */
            stderr: string;
            /**
             * Stdout
             * @default
             */
            stdout: string;
            /** Top Level Pid */
            top_level_pid?: number | null;
        };
        /** AgentRunListResponse */
        AgentRunListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["AgentRun"][];
        };
        /**
         * AgentRunStatus
         * @enum {string}
         */
        AgentRunStatus: "ATTACHED" | "RUNNING" | "PAUSED" | "PASSED" | "FAILED" | "TIMED_OUT" | "CANCELLED" | "ERROR";
        /** AssuranceCheck */
        AssuranceCheck: {
            /** Args */
            args?: string[];
            /** Executable */
            executable: string;
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Rationale */
            rationale: string;
            /**
             * Required
             * @default false
             */
            required: boolean;
        };
        /**
         * AssuranceEvaluation
         * @description Freshness-aware decision inputs for one plan and its runs.
         */
        AssuranceEvaluation: {
            /** Assurance Fresh */
            assurance_fresh: boolean;
            /**
             * Checkpoint Id
             * Format: uuid
             */
            checkpoint_id: string;
            /** Coverage Gaps */
            coverage_gaps?: string[];
            /** Deviations */
            deviations?: components["schemas"]["DeviationFinding"][];
            /** Deviations Resolved */
            deviations_resolved: boolean;
            /** Failed */
            failed?: string[];
            /** Fresh */
            fresh: boolean;
            /** Freshness Reasons */
            freshness_reasons?: string[];
            /** Missing Required */
            missing_required?: string[];
            /**
             * Plan Id
             * Format: uuid
             */
            plan_id: string;
            /** Required Assurance Passed */
            required_assurance_passed: boolean;
            /** Required Evidence Complete */
            required_evidence_complete: boolean;
            /** Results */
            results?: components["schemas"]["CheckResult"][];
            status: components["schemas"]["EvidenceStatus"];
        };
        /**
         * AssuranceFacts
         * @description The ``LifecycleFacts`` fields owned by ``[KB]``, from persisted, fresh evidence.
         */
        AssuranceFacts: {
            /**
             * Assurance Fresh
             * @default false
             */
            assurance_fresh: boolean;
            /**
             * Deviations Resolved
             * @default false
             */
            deviations_resolved: boolean;
            /** Reasons */
            reasons?: string[];
            /**
             * Required Assurance Passed
             * @default false
             */
            required_assurance_passed: boolean;
            /**
             * Required Evidence Complete
             * @default false
             */
            required_evidence_complete: boolean;
        };
        /** AssurancePlan */
        AssurancePlan: {
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /**
             * Checkpoint Id
             * Format: uuid
             */
            checkpoint_id: string;
            /** Checks */
            checks?: components["schemas"]["AssuranceCheck"][];
            /** Coverage Gaps */
            coverage_gaps?: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
        };
        /** AssuranceRun */
        AssuranceRun: {
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Check Id */
            check_id: string;
            /**
             * Checkpoint Id
             * Format: uuid
             */
            checkpoint_id: string;
            /**
             * Completed At
             * Format: date-time
             */
            completed_at: string;
            /** Duration Ms */
            duration_ms: number;
            /** Exit Code */
            exit_code?: number | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Output Truncated
             * @default false
             */
            output_truncated: boolean;
            /**
             * Plan Id
             * Format: uuid
             */
            plan_id: string;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            status: components["schemas"]["AssuranceStatus"];
            /**
             * Stderr
             * @default
             */
            stderr: string;
            /**
             * Stdout
             * @default
             */
            stdout: string;
        };
        /** AssuranceRunActionRequest */
        AssuranceRunActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /**
             * Output Limit Bytes
             * @default 200000
             */
            output_limit_bytes: number;
        };
        /** AssuranceRunListResponse */
        AssuranceRunListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["AssuranceRun"][];
        };
        /**
         * AssuranceStatus
         * @enum {string}
         */
        AssuranceStatus: "PENDING" | "RUNNING" | "PASSED" | "FAILED" | "TIMED_OUT" | "ERROR" | "SKIPPED";
        /**
         * BackendIdentity
         * @description Lets a caller (the desktop app in particular) confirm which backend
         *     process it is actually talking to, not just that some server answered.
         *
         *     ``instance_id`` is generated fresh each time the process starts, so a
         *     stale backend left running behind a killed-and-relaunched desktop app
         *     presents a different id than the freshly launched one -- a stronger
         *     signal than "health + an authenticated call" for detecting exactly that
         *     reap failure.
         */
        BackendIdentity: {
            /** Api Version */
            api_version: string;
            /**
             * Instance Id
             * Format: uuid
             */
            instance_id: string;
            /** Service Name */
            service_name: string;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
        };
        /** CapabilitiesResponse */
        CapabilitiesResponse: {
            /** Items */
            items: components["schemas"]["Capability"][];
        };
        /** Capability */
        Capability: {
            /** Id */
            id: string;
            /** Limitations */
            limitations?: string[];
            /** Name */
            name: string;
            /** Reason */
            reason?: string | null;
            state: components["schemas"]["CapabilityState"];
        };
        /**
         * CapabilityState
         * @enum {string}
         */
        CapabilityState: "AVAILABLE" | "UNCONFIGURED" | "UNSUPPORTED";
        /** ChainVerificationResult */
        ChainVerificationResult: {
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Checked Events */
            checked_events: number;
            /** First Break Seq */
            first_break_seq?: number | null;
            /** Reason */
            reason?: string | null;
            /** Verified */
            verified: boolean;
        };
        /** ChangeCancelRequest */
        ChangeCancelRequest: {
            /** Expected Revision */
            expected_revision: number;
            /** Reason */
            reason?: string | null;
        };
        /** ChangeContract */
        ChangeContract: {
            /** Allowed Paths */
            allowed_paths?: string[];
            /** Allowed Provider Operations */
            allowed_provider_operations?: string[];
            /** Authority Ceiling */
            authority_ceiling?: string[];
            /** Expected Outcomes */
            expected_outcomes?: string[];
            /** Forbidden Paths */
            forbidden_paths?: string[];
            /** @default MEDIUM */
            max_risk: components["schemas"]["RiskLevel"];
            /**
             * Recovery Allowed
             * @default true
             */
            recovery_allowed: boolean;
            /** Required Checks */
            required_checks?: string[];
            /**
             * Schema Version
             * @default 1
             * @constant
             */
            schema_version: 1;
        };
        /** ChangeContractUpdateRequest */
        ChangeContractUpdateRequest: {
            contract: components["schemas"]["ChangeContract"];
            /** Expected Revision */
            expected_revision: number;
        };
        /** ChangeCreateRequest */
        ChangeCreateRequest: {
            contract?: components["schemas"]["ChangeContract"];
            /** Fork From Checkpoint Id */
            fork_from_checkpoint_id?: string | null;
            /** Intent */
            intent: string;
            /** Repository Path */
            repository_path: string;
            /** Title */
            title: string;
        };
        /** ChangeForkActionRequest */
        ChangeForkActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            fork: components["schemas"]["ChangeForkRequest"];
        };
        /** ChangeForkRequest */
        ChangeForkRequest: {
            /**
             * Checkpoint Id
             * Format: uuid
             */
            checkpoint_id: string;
            /** Intent */
            intent: string;
            /** Title */
            title: string;
        };
        /**
         * ChangeLifecycleState
         * @enum {string}
         */
        ChangeLifecycleState: "DRAFT" | "ACTIVE" | "PAUSED" | "LOCALLY_VERIFIED" | "REVIEW_READY" | "PR_OPEN" | "CI_VERIFIED" | "ARTIFACT_BUILT" | "DEPLOYED" | "OBSERVING" | "STABLE" | "BLOCKED" | "FAILED" | "CANCELLED" | "RECOVERY_PENDING" | "RECOVERING" | "RECOVERED_VERIFIED" | "RECOVERY_CONFLICT" | "RECOVERY_FAILED";
        /** ChangeListResponse */
        ChangeListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["ChangeView"][];
            /** Total */
            total: number;
        };
        /** ChangePassport */
        ChangePassport: {
            /** Actor Ids */
            actor_ids?: string[];
            /** Authority Summary */
            authority_summary?: string[];
            /** Canonical Digest */
            canonical_digest: string;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Evidence */
            evidence?: components["schemas"]["EvidenceReference"][];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            lifecycle_state: components["schemas"]["ChangeLifecycleState"];
            /** Limitations */
            limitations?: string[];
            /** Outcomes */
            outcomes?: string[];
            recovery_status?: components["schemas"]["RecoveryStatus"] | null;
            /** Replay Checked Events */
            replay_checked_events?: number | null;
            /** Replay First Break Seq */
            replay_first_break_seq?: number | null;
            /** Replay Verified */
            replay_verified?: boolean | null;
            /**
             * Schema Version
             * @default 1
             * @constant
             */
            schema_version: 1;
            /** Tool Trust Summary */
            tool_trust_summary?: components["schemas"]["ToolTrustSummaryEntry"][];
        };
        /** ChangeTransitionRequest */
        ChangeTransitionRequest: {
            /** Expected Revision */
            expected_revision: number;
            /** Reason */
            reason?: string | null;
            target_state: components["schemas"]["ChangeLifecycleState"];
        };
        /** ChangeView */
        ChangeView: {
            /**
             * Allowed Next States
             * @description States the lifecycle state machine permits transitioning to from the current state. This reflects the transition graph only, not whether the target's guard conditions currently pass -- a transition to a listed state can still fail with 409 TRANSITION_GUARD_FAILED (see GET .../assurance/facts and the transition response's missing_requirements for guard detail).
             */
            allowed_next_states?: components["schemas"]["ChangeLifecycleState"][];
            contract?: components["schemas"]["ChangeContract"];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Evidence Revision
             * @default 0
             */
            evidence_revision: number;
            /** Forked From Change Id */
            forked_from_change_id?: string | null;
            /** Forked From Checkpoint Id */
            forked_from_checkpoint_id?: string | null;
            git_summary?: components["schemas"]["GitSummary"] | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Intent */
            intent: string;
            /** Last Refreshed At */
            last_refreshed_at?: string | null;
            /** Last Transition At */
            last_transition_at?: string | null;
            /** @default DRAFT */
            lifecycle_state: components["schemas"]["ChangeLifecycleState"];
            /** Repository Path */
            repository_path: string;
            review_state: components["schemas"]["ReviewState"];
            /**
             * Revision
             * @default 1
             */
            revision: number;
            /** @default UNKNOWN */
            risk_level: components["schemas"]["RiskLevel"];
            /** Title */
            title: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            verification?: components["schemas"]["VerificationResult"] | null;
            /** Verification Evidence Revision */
            verification_evidence_revision?: number | null;
        };
        /** ChangedPath */
        ChangedPath: {
            /** Additions */
            additions?: number | null;
            /**
             * Binary
             * @default false
             */
            binary: boolean;
            category: components["schemas"]["PathCategory"];
            /** Deletions */
            deletions?: number | null;
            /** Old Path */
            old_path?: string | null;
            /** Path */
            path: string;
            /** Staged */
            staged: boolean;
            status: components["schemas"]["ChangedPathStatus"];
            /** Unstaged */
            unstaged: boolean;
        };
        /**
         * ChangedPathStatus
         * @enum {string}
         */
        ChangedPathStatus: "ADDED" | "MODIFIED" | "DELETED" | "RENAMED" | "COPIED" | "UNTRACKED" | "CONFLICTED";
        /** CheckResult */
        CheckResult: {
            /** Check Id */
            check_id: string;
            /** Exit Code */
            exit_code?: number | null;
            /** Required */
            required: boolean;
            status: components["schemas"]["AssuranceStatus"];
            /**
             * Summary
             * @default
             */
            summary: string;
        };
        /** CredentialGrant */
        CredentialGrant: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /** Provider */
            provider: string;
            /** Revoked At */
            revoked_at?: string | null;
            /** Scopes */
            scopes: string[];
        };
        /** CredentialGrantRequest */
        CredentialGrantRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /** Scopes */
            scopes: string[];
            /**
             * Ttl Seconds
             * @default 900
             */
            ttl_seconds: number;
        };
        /** Delegation */
        Delegation: {
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /**
             * Grantee Id
             * Format: uuid
             */
            grantee_id: string;
            /**
             * Grantor Id
             * Format: uuid
             */
            grantor_id: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /** Repository Path */
            repository_path: string;
            /** Revoked At */
            revoked_at?: string | null;
            /** Scopes */
            scopes: string[];
            /** Use Limit */
            use_limit?: number | null;
            /**
             * Uses
             * @default 0
             */
            uses: number;
        };
        /** DelegationCreateRequest */
        DelegationCreateRequest: {
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /**
             * Grantee Id
             * Format: uuid
             */
            grantee_id: string;
            /**
             * Grantor Id
             * Format: uuid
             */
            grantor_id: string;
            /** Scopes */
            scopes: string[];
            /** Ttl Seconds */
            ttl_seconds: number;
            /** Use Limit */
            use_limit?: number | null;
        };
        /** DelegationListResponse */
        DelegationListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["Delegation"][];
        };
        /** DependencyChange */
        DependencyChange: {
            /**
             * Causal Attribution Available
             * @default false
             * @constant
             */
            causal_attribution_available: false;
            /** Direct */
            direct?: boolean | null;
            /** Ecosystem */
            ecosystem: string;
            /** @default CURRENT */
            evidence_status: components["schemas"]["EvidenceStatus"];
            /** New Version */
            new_version?: string | null;
            /** Old Version */
            old_version?: string | null;
            /** Package */
            package: string;
            /** Risk Notes */
            risk_notes?: string[];
            /** Source Path */
            source_path: string;
        };
        /** DependencyReport */
        DependencyReport: {
            /**
             * Captured At
             * Format: date-time
             */
            captured_at: string;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Changes */
            changes?: components["schemas"]["DependencyChange"][];
            /**
             * Checkpoint Id
             * Format: uuid
             */
            checkpoint_id: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Unsupported Ecosystems */
            unsupported_ecosystems?: string[];
        };
        /**
         * DeviationCategory
         * @enum {string}
         */
        DeviationCategory: "FORBIDDEN_PATH" | "OUTSIDE_ALLOWED_PATHS" | "MERGE_CONFLICT" | "RISK_ABOVE_CEILING" | "RISK_NOT_ASSESSED" | "DEPENDENCY_CHANGE" | "DEPENDENCY_EVIDENCE_GAP" | "ENVIRONMENT_DRIFT";
        /** DeviationFinding */
        DeviationFinding: {
            category: components["schemas"]["DeviationCategory"];
            /** Detail */
            detail: string;
            severity: components["schemas"]["DeviationSeverity"];
            /** Subject */
            subject: string;
        };
        /**
         * DeviationSeverity
         * @enum {string}
         */
        DeviationSeverity: "BLOCKING" | "WARNING" | "INFO";
        /** EnvironmentDrift */
        EnvironmentDrift: {
            /** Added */
            added?: components["schemas"]["EnvironmentFact"][];
            /**
             * Baseline Id
             * Format: uuid
             */
            baseline_id: string;
            /**
             * Causal Attribution Available
             * @default false
             * @constant
             */
            causal_attribution_available: false;
            /** Changed */
            changed?: components["schemas"]["EnvironmentFact"][];
            /**
             * Current Id
             * Format: uuid
             */
            current_id: string;
            /** Removed */
            removed?: components["schemas"]["EnvironmentFact"][];
            /** Unknown */
            unknown?: components["schemas"]["EnvironmentFact"][];
        };
        /** EnvironmentFact */
        EnvironmentFact: {
            /** Fingerprint */
            fingerprint?: string | null;
            /** Key */
            key: string;
            /**
             * Sensitive
             * @default false
             */
            sensitive: boolean;
            /** @default CURRENT */
            status: components["schemas"]["EvidenceStatus"];
            /** Value */
            value?: string | null;
        };
        /** EnvironmentPassport */
        EnvironmentPassport: {
            /**
             * Captured At
             * Format: date-time
             */
            captured_at: string;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Facts */
            facts?: components["schemas"]["EnvironmentFact"][];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Limitations */
            limitations?: string[];
            /**
             * Schema Version
             * @default 1
             * @constant
             */
            schema_version: 1;
            /** @default CURRENT */
            status: components["schemas"]["EvidenceStatus"];
        };
        /**
         * EnvironmentView
         * @description The latest environment passport and its drift from the first one captured.
         */
        EnvironmentView: {
            /** Baseline Id */
            baseline_id?: string | null;
            drift?: components["schemas"]["EnvironmentDrift"] | null;
            passport?: components["schemas"]["EnvironmentPassport"] | null;
        };
        /**
         * EvidenceOverview
         * @description What has been captured so far for one Change (read-only).
         */
        EvidenceOverview: {
            /** Baseline Captured */
            baseline_captured: boolean;
            /** Checkpoints */
            checkpoints?: components["schemas"]["GitCheckpoint"][];
            dependencies?: components["schemas"]["DependencyReport"] | null;
            environment?: components["schemas"]["EnvironmentPassport"] | null;
            /** Latest Checkpoint Fresh */
            latest_checkpoint_fresh?: boolean | null;
            plan?: components["schemas"]["AssurancePlan"] | null;
        };
        /** EvidenceReference */
        EvidenceReference: {
            /** Captured At */
            captured_at?: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Kind */
            kind: string;
            status: components["schemas"]["EvidenceStatus"];
        };
        /**
         * EvidenceSnapshot
         * @description Everything captured at one point in time, with comparisons to the baseline.
         */
        EvidenceSnapshot: {
            checkpoint: components["schemas"]["GitCheckpoint"];
            comparison?: components["schemas"]["GitCheckpointComparison"] | null;
            dependencies?: components["schemas"]["DependencyReport"] | null;
            drift?: components["schemas"]["EnvironmentDrift"] | null;
            environment: components["schemas"]["EnvironmentPassport"];
            /** Limitations */
            limitations?: string[];
        };
        /**
         * EvidenceStatus
         * @enum {string}
         */
        EvidenceStatus: "CURRENT" | "STALE" | "MISSING" | "UNSUPPORTED" | "PARTIAL";
        /** GitCheckpoint */
        GitCheckpoint: {
            /** Branch */
            branch?: string | null;
            /**
             * Captured At
             * Format: date-time
             */
            captured_at: string;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Evidence Revision */
            evidence_revision: number;
            /** Head Sha */
            head_sha: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Repository Root */
            repository_root: string;
            /** Status Digest */
            status_digest: string;
            summary: components["schemas"]["GitSummary"];
        };
        /** GitCheckpointComparison */
        GitCheckpointComparison: {
            /** Added Paths */
            added_paths?: string[];
            /**
             * Baseline Id
             * Format: uuid
             */
            baseline_id: string;
            /** Branch Moved */
            branch_moved: boolean;
            /** Changed Paths */
            changed_paths?: string[];
            /**
             * Current Id
             * Format: uuid
             */
            current_id: string;
            /** Head Changed */
            head_changed: boolean;
            /** Removed Paths */
            removed_paths?: string[];
        };
        /** GitCheckpointListResponse */
        GitCheckpointListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["GitCheckpoint"][];
        };
        /** GitSummary */
        GitSummary: {
            /** Branch */
            branch?: string | null;
            /** Files */
            files?: components["schemas"]["ChangedPath"][];
            /** Head Sha */
            head_sha: string;
            /** Is Clean */
            is_clean: boolean;
            /** Patch */
            patch: string;
            /**
             * Patch Truncated
             * @default false
             */
            patch_truncated: boolean;
            /**
             * Refreshed At
             * Format: date-time
             */
            refreshed_at: string;
            /** Repository Root */
            repository_root: string;
            /** Total Additions */
            total_additions: number;
            /** Total Deletions */
            total_deletions: number;
            /**
             * Untracked Patch Omitted
             * @default false
             */
            untracked_patch_omitted: boolean;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /** Api Version */
            api_version: string;
            /** Status */
            status: string;
        };
        /**
         * JournalEffect
         * @description A structured before/produced digest transition attached to one event.
         *
         *     Narrower than the PDF's generic filesystem/process effect model: only
         *     covers resources that already carry a comparable digest today (see A.2).
         */
        JournalEffect: {
            /** Before Digest */
            before_digest?: string | null;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /**
             * Event Id
             * Format: uuid
             */
            event_id: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Produced Digest */
            produced_digest?: string | null;
            /**
             * Resource Id
             * Format: uuid
             */
            resource_id: string;
            /** Resource Type */
            resource_type: string;
            restoration_class: components["schemas"]["RestorationClass"];
        };
        /**
         * JournalEvent
         * @description One immutable, hash-chained row in a Change's causal timeline.
         *
         *     The chain is scoped per Change (`seq` is monotonic within `change_id`,
         *     starting at 1): see A.3/A.7 of the plan for why, and for the explicit
         *     limitation that this proves within-Change tamper evidence only, not
         *     cross-Change tamper evidence.
         */
        JournalEvent: {
            /** Actor Id */
            actor_id?: string | null;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Event Hash */
            event_hash: string;
            event_type: components["schemas"]["JournalEventType"];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Payload */
            payload?: {
                [key: string]: unknown;
            };
            /** Prev Event Hash */
            prev_event_hash?: string | null;
            /**
             * Schema Version
             * @default 1
             */
            schema_version: number;
            /** Seq */
            seq: number;
            /** Subject Id */
            subject_id?: string | null;
            /** Subject Type */
            subject_type?: string | null;
        };
        /** JournalEventListResponse */
        JournalEventListResponse: {
            /** Count */
            count: number;
            /** Items */
            items?: components["schemas"]["JournalEvent"][];
        };
        /**
         * JournalEventType
         * @description Closed, namespaced set of mutations this backend can honestly journal.
         *
         *     Every member corresponds to a mutation of an entity this backend already
         *     models (see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` Part A). There is no
         *     `filesystem.write` or `process.spawn` member: the filesystem tracker and
         *     process supervisor stay cut, so those effects are never claimed here.
         * @enum {string}
         */
        JournalEventType: "change.created" | "change.contract_updated" | "change.transitioned" | "change.git_summary_refreshed" | "change.legacy_verification_run" | "change.deleted" | "delegation.issued" | "delegation.revoked" | "credential.grant.issued" | "credential.grant.revoked" | "credential.secret.resolved" | "git.checkpoint.captured" | "agent.launched" | "agent.attached" | "agent.stop_requested" | "agent.completed" | "environment.passport.captured" | "dependency.report.captured" | "assurance.plan.created" | "assurance.check.completed" | "provider.pull_request.created" | "provider.pull_request.refreshed" | "provider.pull_request.closed" | "provider.ci_refreshed" | "outcome.recorded" | "recovery.plan.created" | "recovery.action.completed" | "recovery.plan.completed" | "passport.built" | "policy.decision.denied" | "tool.manifest.registered" | "tool.trust.decided" | "tool.trust.invalidated" | "agent.paused" | "agent.resumed" | "change.forked";
        /** Outcome */
        Outcome: {
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Details */
            details?: {
                [key: string]: unknown;
            };
            /** Head Sha */
            head_sha: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            kind: components["schemas"]["OutcomeKind"];
            /**
             * Observed At
             * Format: date-time
             */
            observed_at: string;
            /** Provider Reference */
            provider_reference: string;
            /** Repository */
            repository: string;
            status: components["schemas"]["OutcomeStatus"];
        };
        /**
         * OutcomeKind
         * @enum {string}
         */
        OutcomeKind: "PULL_REQUEST" | "CI" | "ARTIFACT" | "DEPLOYMENT";
        /** OutcomeListResponse */
        OutcomeListResponse: {
            /** Count */
            count: number;
            /** Items */
            items: components["schemas"]["Outcome"][];
        };
        /** OutcomeRefreshRequest */
        OutcomeRefreshRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /**
             * Grant Id
             * Format: uuid
             */
            grant_id: string;
            /** Required Check Names */
            required_check_names?: string[];
        };
        /**
         * OutcomeStatus
         * @enum {string}
         */
        OutcomeStatus: "UNKNOWN" | "PENDING" | "PASSED" | "FAILED" | "CANCELLED" | "UNAVAILABLE";
        /**
         * PathCategory
         * @enum {string}
         */
        PathCategory: "SOURCE" | "TEST" | "DEPENDENCY" | "CONFIG" | "DOCUMENTATION" | "OTHER";
        /** ProviderConnectRequest */
        ProviderConnectRequest: {
            /** Token */
            token: string;
        };
        /** ProviderConnectionStatus */
        ProviderConnectionStatus: {
            /** Configured */
            configured: boolean;
            /** Provider */
            provider: string;
        };
        /** ProviderOperation */
        ProviderOperation: {
            /** Completed At */
            completed_at?: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Provider Reference */
            provider_reference?: string | null;
            request: components["schemas"]["ProviderOperationRequest"];
            /** Safe Metadata */
            safe_metadata?: {
                [key: string]: unknown;
            };
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            status: components["schemas"]["ProviderOperationStatus"];
        };
        /** ProviderOperationRequest */
        ProviderOperationRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Idempotency Key */
            idempotency_key: string;
            /** Operation */
            operation: string;
            /** Parameters */
            parameters?: {
                [key: string]: unknown;
            };
            /** Provider */
            provider: string;
        };
        /**
         * ProviderOperationStatus
         * @enum {string}
         */
        ProviderOperationStatus: "PENDING" | "SUCCEEDED" | "FAILED" | "PARTIAL" | "DENIED";
        /** PullRequestActionRequest */
        PullRequestActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /** Base Branch */
            base_branch: string;
            /**
             * Grant Id
             * Format: uuid
             */
            grant_id: string;
            /** Head Branch */
            head_branch: string;
            /** Idempotency Key */
            idempotency_key: string;
            /** Title */
            title: string;
        };
        /** PullRequestCloseActionRequest */
        PullRequestCloseActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /**
             * Grant Id
             * Format: uuid
             */
            grant_id: string;
            /** Idempotency Key */
            idempotency_key: string;
        };
        /** RecoveryAction */
        RecoveryAction: {
            /** Description */
            description: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Kind */
            kind: string;
            /** Limitations */
            limitations?: string[];
            /** Provider Reference */
            provider_reference?: string | null;
            /** Reversible Commit */
            reversible_commit?: string | null;
            /** Supported */
            supported: boolean;
        };
        /** RecoveryExecuteRequest */
        RecoveryExecuteRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /** Approval Token */
            approval_token: string;
        };
        /** RecoveryPlan */
        RecoveryPlan: {
            /** Actions */
            actions?: components["schemas"]["RecoveryAction"][];
            /** Approved At */
            approved_at?: string | null;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Completed At */
            completed_at?: string | null;
            /** Conflicts */
            conflicts?: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Source Checkpoint Id
             * Format: uuid
             */
            source_checkpoint_id: string;
            /** @default PLANNED */
            status: components["schemas"]["RecoveryStatus"];
            /** Unsupported Effects */
            unsupported_effects?: string[];
        };
        /**
         * RecoveryStatus
         * @enum {string}
         */
        RecoveryStatus: "PLANNED" | "APPROVED" | "EXECUTING" | "RECOVERED" | "PARTIAL" | "RECOVERY_FAILED" | "CONFLICTED";
        /**
         * ReplayTimeline
         * @description Deterministic reconstruction of a Change's causal timeline.
         *
         *     Trace-only: no re-execution of any kind. See A.7 for the full list of
         *     explicit non-goals, echoed in `limitations` on every response.
         */
        ReplayTimeline: {
            /** Chain Verified */
            chain_verified: boolean;
            /**
             * Change Id
             * Format: uuid
             */
            change_id: string;
            /** Effects */
            effects?: components["schemas"]["JournalEffect"][];
            /** Events */
            events?: components["schemas"]["JournalEvent"][];
            /** First Break Seq */
            first_break_seq?: number | null;
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Limitations */
            limitations?: string[];
        };
        /** RepositoryInfo */
        RepositoryInfo: {
            /** Branch */
            branch?: string | null;
            /** Head Sha */
            head_sha: string;
            /** Root */
            root: string;
        };
        /** RepositoryPathRequest */
        RepositoryPathRequest: {
            /** Path */
            path: string;
        };
        /**
         * RestorationClass
         * @enum {string}
         */
        RestorationClass: "exact" | "conditional" | "compensating" | "stageable" | "none" | "unknown";
        /**
         * ReviewState
         * @enum {string}
         */
        ReviewState: "NO_CHANGES" | "MISSING_EVIDENCE" | "FAILED_VERIFICATION" | "READY_FOR_HUMAN_REVIEW";
        /**
         * RiskLevel
         * @enum {string}
         */
        RiskLevel: "UNKNOWN" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
        /** ToolDeclareRequest */
        ToolDeclareRequest: {
            /** Manifest Path */
            manifest_path: string;
        };
        /**
         * ToolManifest
         * @description A top-level launched executable or explicitly declared tool/MCP
         *     manifest (see EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md B.1's bounded
         *     scope -- this governs what top-level executable may launch, never what
         *     a running agent's descendant process calls).
         */
        ToolManifest: {
            /** Artifact Digest */
            artifact_digest: string;
            /** Capabilities */
            capabilities?: string[];
            /** Credential Requirements */
            credential_requirements?: string[];
            /** Filesystem Scope */
            filesystem_scope?: string[];
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at: string;
            /** Name */
            name: string;
            /** Network Scope */
            network_scope?: string[];
            /** Publisher */
            publisher?: string | null;
            signature_state: components["schemas"]["ToolSignatureState"];
            /** Source */
            source: string;
            trust_state: components["schemas"]["ToolTrustState"];
            /** Version */
            version: string;
        };
        /** ToolManifestListResponse */
        ToolManifestListResponse: {
            /** Count */
            count: number;
            /** Items */
            items?: components["schemas"]["ToolManifest"][];
        };
        /**
         * ToolSignatureState
         * @enum {string}
         */
        ToolSignatureState: "valid" | "invalid" | "unsigned" | "unknown";
        /** ToolTrustDecision */
        ToolTrustDecision: {
            /** Change Id */
            change_id?: string | null;
            /**
             * Decided At
             * Format: date-time
             */
            decided_at: string;
            /**
             * Decided By Actor Id
             * Format: uuid
             */
            decided_by_actor_id: string;
            decision: components["schemas"]["ToolTrustDecisionKind"];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Invalidated At */
            invalidated_at?: string | null;
            /** Invalidation Reason */
            invalidation_reason?: string | null;
            /** Reason */
            reason?: string | null;
            scope: components["schemas"]["ToolTrustScope"];
            /**
             * Tool Id
             * Format: uuid
             */
            tool_id: string;
        };
        /**
         * ToolTrustDecisionKind
         * @enum {string}
         */
        ToolTrustDecisionKind: "APPROVE" | "DENY";
        /** ToolTrustRequest */
        ToolTrustRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            /** Change Id */
            change_id?: string | null;
            decision: components["schemas"]["ToolTrustDecisionKind"];
            /** Reason */
            reason?: string | null;
            scope: components["schemas"]["ToolTrustScope"];
        };
        /**
         * ToolTrustScope
         * @enum {string}
         */
        ToolTrustScope: "exact_version" | "publisher_policy";
        /**
         * ToolTrustState
         * @enum {string}
         */
        ToolTrustState: "UNKNOWN" | "OBSERVED" | "PROVISIONAL" | "APPROVED" | "DENIED";
        /**
         * ToolTrustSummaryEntry
         * @description One tool observed for a Change, as surfaced on the Change Passport.
         *
         *     Mirrors the PDF §30 Passport "TOOLS" block (e.g. `Codex CLI: approved`)
         *     but built from real `ToolManifest`/`DriftReport` data (see
         *     EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md §B.8) rather than a placeholder.
         */
        ToolTrustSummaryEntry: {
            /** Drifted */
            drifted: boolean;
            /** Name */
            name: string;
            /** Publisher */
            publisher?: string | null;
            signature_state: components["schemas"]["ToolSignatureState"];
            /**
             * Tool Id
             * Format: uuid
             */
            tool_id: string;
            trust_state: components["schemas"]["ToolTrustState"];
            /** Version */
            version: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** VerificationActionRequest */
        VerificationActionRequest: {
            /**
             * Actor Id
             * Format: uuid
             */
            actor_id: string;
            verification: components["schemas"]["VerificationRequest"];
        };
        /** VerificationRequest */
        VerificationRequest: {
            /** Args */
            args?: string[];
            /** Executable */
            executable: string;
            /**
             * Timeout Seconds
             * @default 120
             */
            timeout_seconds: number;
        };
        /** VerificationResult */
        VerificationResult: {
            /** Args */
            args?: string[];
            /**
             * Completed At
             * Format: date-time
             */
            completed_at: string;
            /** Duration Ms */
            duration_ms: number;
            /** Executable */
            executable: string;
            /** Exit Code */
            exit_code?: number | null;
            /**
             * Output Truncated
             * @default false
             */
            output_truncated: boolean;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            status: components["schemas"]["VerificationStatus"];
            /** Stderr */
            stderr: string;
            /** Stdout */
            stdout: string;
        };
        /**
         * VerificationStatus
         * @enum {string}
         */
        VerificationStatus: "PASSED" | "FAILED" | "TIMED_OUT" | "ERROR";
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_actors_api_v1_actors_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActorListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_actor_api_v1_actors_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActorCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Actor"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_actor_api_v1_actors__actor_id__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                actor_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Actor"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_agent_adapters_api_v1_agents_adapters_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentAdapterListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    capabilities_api_v1_capabilities_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapabilitiesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_changes_api_v1_changes_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_change_api_v1_changes_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChangeCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_change_api_v1_changes__change_id__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_change_api_v1_changes__change_id__delete: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_agent_runs_api_v1_changes__change_id__agents_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRunListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    attach_agent_api_v1_changes__change_id__agents_attach_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentAttachActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRun"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    launch_agent_api_v1_changes__change_id__agents_launch_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AgentLaunchActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRun"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pause_agent_api_v1_changes__change_id__agents__run_id__pause_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActorActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRun"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resume_agent_api_v1_changes__change_id__agents__run_id__resume_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActorActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRun"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stop_agent_api_v1_changes__change_id__agents__run_id__stop_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActorActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRun"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_assurance_facts_api_v1_changes__change_id__assurance_facts_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssuranceFacts"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_latest_assurance_plan_api_v1_changes__change_id__assurance_plan_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssurancePlan"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    plan_assurance_api_v1_changes__change_id__assurance_plan_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssurancePlan"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    evaluate_assurance_api_v1_changes__change_id__assurance__plan_id__evaluation_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssuranceEvaluation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    run_assurance_api_v1_changes__change_id__assurance__plan_id__run_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssuranceRunActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssuranceRunListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_change_api_v1_changes__change_id__cancel_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChangeCancelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_change_contract_api_v1_changes__change_id__contract_put: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChangeContractUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_delegations_api_v1_changes__change_id__delegations_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DelegationListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_dependencies_api_v1_changes__change_id__dependencies_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyReport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_environment_api_v1_changes__change_id__environment_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnvironmentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_journal_events_api_v1_changes__change_id__events_get: {
        parameters: {
            query?: {
                event_type?: components["schemas"]["JournalEventType"] | null;
                since_seq?: number;
                limit?: number;
            };
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JournalEventListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_evidence_api_v1_changes__change_id__evidence_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EvidenceOverview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    capture_baseline_api_v1_changes__change_id__evidence_baseline_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EvidenceSnapshot"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    capture_current_evidence_api_v1_changes__change_id__evidence_current_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EvidenceSnapshot"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    fork_change_api_v1_changes__change_id__fork_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChangeForkActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_change_forks_api_v1_changes__change_id__forks_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_git_checkpoints_api_v1_changes__change_id__git_checkpoints_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GitCheckpointListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    compare_git_checkpoints_api_v1_changes__change_id__git_compare_get: {
        parameters: {
            query: {
                baseline_id: string;
                current_id: string;
            };
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GitCheckpointComparison"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_outcomes_api_v1_changes__change_id__outcomes_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OutcomeListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_outcomes_api_v1_changes__change_id__outcomes_refresh_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OutcomeRefreshRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OutcomeListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_latest_passport_api_v1_changes__change_id__passport_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangePassport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    build_passport_api_v1_changes__change_id__passport_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangePassport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    issue_github_grant_api_v1_changes__change_id__providers_github_grants_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CredentialGrantRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CredentialGrant"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_github_grant_api_v1_changes__change_id__providers_github_grants__grant_id__revoke_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CredentialGrant"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_pull_request_api_v1_changes__change_id__providers_github_pulls_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PullRequestActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderOperation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    close_pull_request_api_v1_changes__change_id__providers_github_pulls_close_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PullRequestCloseActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderOperation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_latest_recovery_api_v1_changes__change_id__recovery_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecoveryPlan"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_recovery_api_v1_changes__change_id__recovery_preview_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecoveryPlan"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    execute_recovery_api_v1_changes__change_id__recovery__plan_id__execute_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
                plan_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecoveryExecuteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecoveryPlan"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_change_api_v1_changes__change_id__refresh_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_replay_api_v1_changes__change_id__replay_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReplayTimeline"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_replay_api_v1_changes__change_id__replay_export_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReplayTimeline"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_replay_api_v1_changes__change_id__replay_verify_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChainVerificationResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_tools_for_change_api_v1_changes__change_id__tools_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolManifestListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    declare_tool_manifest_api_v1_changes__change_id__tools_declare_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ToolDeclareRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolManifest"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    transition_change_api_v1_changes__change_id__transition_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChangeTransitionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_change_api_v1_changes__change_id__verify_post: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
                Authorization?: string | null;
            };
            path: {
                change_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VerificationActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_delegation_api_v1_delegations_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DelegationCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Delegation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_delegation_api_v1_delegations__delegation_id__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                delegation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Delegation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_delegation_api_v1_delegations__delegation_id__revoke_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                delegation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Delegation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_v1_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    connect_github_api_v1_providers_github_connect_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProviderConnectRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderConnectionStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    disconnect_github_api_v1_providers_github_disconnect_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderConnectionStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    github_status_api_v1_providers_github_status_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderConnectionStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_repository_api_v1_repositories_validate_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RepositoryPathRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepositoryInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    backend_identity_api_v1_system_backend_identity_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BackendIdentity"];
                };
            };
        };
    };
    list_tools_api_v1_tools_get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolManifestListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_tool_api_v1_tools__tool_id__get: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                tool_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolManifest"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decide_tool_trust_api_v1_tools__tool_id__trust_post: {
        parameters: {
            query?: never;
            header?: {
                Authorization?: string | null;
            };
            path: {
                tool_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ToolTrustRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolTrustDecision"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
