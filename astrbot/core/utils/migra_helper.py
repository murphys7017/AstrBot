from astrbot.core import astrbot_config, logger
from astrbot.core.agent.runners.deerflow.constants import DEERFLOW_PROVIDER_TYPE
from astrbot.core.astrbot_config_mgr import AstrBotConfig, AstrBotConfigManager
from astrbot.core.db.migration.migra_45_to_46 import migrate_45_to_46
from astrbot.core.db.migration.migra_token_usage import migrate_token_usage
from astrbot.core.db.migration.migra_webchat_session import migrate_webchat_session


def _migra_agent_runner_configs(conf: AstrBotConfig, ids_map: dict) -> None:
    """
    Migra agent runner configs from provider configs.
    """
    provider_settings = conf.get("provider_settings", {})
    if not isinstance(provider_settings, dict):
        return

    default_prov_id = provider_settings.get("default_provider_id")
    if default_prov_id not in ids_map:
        return

    provider_settings["default_provider_id"] = ""
    provider = ids_map[default_prov_id]
    runner_type = str(provider.get("type") or "").lower()
    if runner_type in {"dify", "coze", "dashscope", DEERFLOW_PROVIDER_TYPE}:
        conf["agent_runner"] = {
            "mode": runner_type,
            "provider_id": provider["id"],
        }
    conf.save_config()


def _migra_provider_to_source_structure(conf: AstrBotConfig) -> None:
    """
    Migrate old provider structure to new provider-source separation.
    Provider only keeps: id, provider_source_id, model, modalities, custom_extra_body
    All other fields move to provider_sources.
    """
    providers = conf.get("provider", [])
    provider_sources = conf.get("provider_sources", [])

    # Track if any migration happened
    migrated = False

    # Provider-only fields that should stay in provider
    provider_only_fields = {
        "id",
        "provider_source_id",
        "model",
        "modalities",
        "custom_extra_body",
        "enable",
    }

    # Fields that should not go to source
    source_exclude_fields = provider_only_fields | {"model_config"}

    for provider in providers:
        # Skip if already has provider_source_id
        if provider.get("provider_source_id"):
            continue

        # Skip non-chat-completion types (they don't need source separation)
        provider_type = provider.get("provider_type", "")
        if provider_type != "chat_completion":
            # For old types without provider_type, check type field
            old_type = provider.get("type", "")
            if "chat_completion" not in old_type:
                continue

        migrated = True
        logger.info(f"Migrating provider {provider.get('id')} to new structure")

        # Extract source fields from provider
        source_fields = {}
        for key, value in list(provider.items()):
            if key not in source_exclude_fields:
                source_fields[key] = value

        # Create new provider_source
        source_id = provider.get("id", "") + "_source"
        new_source = {"id": source_id, **source_fields}

        # Update provider to only keep necessary fields
        provider["provider_source_id"] = source_id

        # Extract model from model_config if exists
        if "model_config" in provider and isinstance(provider["model_config"], dict):
            model_config = provider["model_config"]
            provider["model"] = model_config.get("model", "")

            # Put other model_config fields into custom_extra_body
            extra_body_fields = {k: v for k, v in model_config.items() if k != "model"}
            if extra_body_fields:
                if "custom_extra_body" not in provider:
                    provider["custom_extra_body"] = {}
                provider["custom_extra_body"].update(extra_body_fields)

        # Initialize new fields if not present
        if "modalities" not in provider:
            provider["modalities"] = []
        if "custom_extra_body" not in provider:
            provider["custom_extra_body"] = {}

        # Remove fields that should be in source
        keys_to_remove = [k for k in provider.keys() if k not in provider_only_fields]
        for key in keys_to_remove:
            del provider[key]

        # Add source to provider_sources
        provider_sources.append(new_source)

    if migrated:
        conf["provider_sources"] = provider_sources
        conf.save_config()
        logger.info("Provider-source structure migration completed")


async def migra(
    db, astrbot_config_mgr, umop_config_router, acm: AstrBotConfigManager
) -> None:
    """
    Stores the migration logic here.
    btw, i really don't like migration :(
    """
    # Required migrations run before runtime services and must fail startup
    # when persisted state cannot be brought to the current schema.
    await migrate_45_to_46(astrbot_config_mgr, umop_config_router)
    await migrate_webchat_session(db)
    await migrate_token_usage(db)

    # migra third party agent runner configs
    _c = False
    providers = astrbot_config["provider"]
    ids_map = {}
    for prov in providers:
        type_ = prov.get("type")
        if type_ in ["dify", "coze", "dashscope", DEERFLOW_PROVIDER_TYPE]:
            prov["provider_type"] = "agent_runner"
            ids_map[prov["id"]] = {
                "type": type_,
                "id": prov["id"],
            }
            _c = True
    if _c:
        astrbot_config.save_config()

    for conf in acm.confs.values():
        _migra_agent_runner_configs(conf, ids_map)

    # Migrate providers to new structure: extract source fields to provider_sources
    _migra_provider_to_source_structure(astrbot_config)
