from sqlmodel import Session, select
from app.models.models import ModelConfig
from app.schemas.schemas import ModelConfigCreate, ModelConfigUpdate
from typing import List, Optional


def _clear_other_defaults(session: Session, model_type: str, keep_id: Optional[int] = None) -> None:
    statement = select(ModelConfig).where(
        ModelConfig.model_type == model_type,
        ModelConfig.is_default == True,  # noqa: E712
    )
    for row in session.exec(statement).all():
        if keep_id is not None and row.id == keep_id:
            continue
        row.is_default = False
        session.add(row)


def _ensure_default_consistency(session: Session, db_config: ModelConfig) -> None:
    """默认必须启用；设为默认时取消同类型其它默认。"""
    if db_config.is_default and not db_config.is_active:
        # 关闭启用时不能继续当默认
        db_config.is_default = False

    if db_config.is_default:
        _clear_other_defaults(session, db_config.model_type, keep_id=db_config.id)
        return

    # 若本类型没有任何默认，把当前启用配置（或本条）扶正为默认
    existing_default = session.exec(
        select(ModelConfig).where(
            ModelConfig.model_type == db_config.model_type,
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.is_active == True,  # noqa: E712
        )
    ).first()
    if existing_default:
        return

    if db_config.is_active:
        db_config.is_default = True
        return

    fallback = session.exec(
        select(ModelConfig)
        .where(
            ModelConfig.model_type == db_config.model_type,
            ModelConfig.is_active == True,  # noqa: E712
        )
        .order_by(ModelConfig.id.asc())
    ).first()
    if fallback:
        fallback.is_default = True
        session.add(fallback)


def create_model_config(session: Session, config_in: ModelConfigCreate) -> ModelConfig:
    db_config = ModelConfig.model_validate(config_in)
    # 同类型尚无默认且本条启用 → 自动成为默认
    has_default = session.exec(
        select(ModelConfig).where(
            ModelConfig.model_type == db_config.model_type,
            ModelConfig.is_default == True,  # noqa: E712
        )
    ).first()
    if db_config.is_active and not has_default:
        db_config.is_default = True
    if db_config.is_default and not db_config.is_active:
        db_config.is_default = False

    session.add(db_config)
    session.flush()
    if db_config.is_default:
        _clear_other_defaults(session, db_config.model_type, keep_id=db_config.id)
    session.commit()
    session.refresh(db_config)
    return db_config


def get_model_configs(session: Session, skip: int = 0, limit: int = 100) -> List[ModelConfig]:
    statement = select(ModelConfig).offset(skip).limit(limit)
    return session.exec(statement).all()


def get_model_config(session: Session, config_id: int) -> Optional[ModelConfig]:
    return session.get(ModelConfig, config_id)


def update_model_config(session: Session, db_config: ModelConfig, config_in: ModelConfigUpdate) -> ModelConfig:
    config_data = config_in.model_dump(exclude_unset=True)
    for key, value in config_data.items():
        setattr(db_config, key, value)

    # 显式设为默认时强制启用
    if config_data.get("is_default") is True:
        db_config.is_active = True
        db_config.is_default = True

    _ensure_default_consistency(session, db_config)
    session.add(db_config)
    session.commit()
    session.refresh(db_config)
    return db_config


def delete_model_config(session: Session, db_config: ModelConfig):
    model_type = db_config.model_type
    was_default = db_config.is_default
    session.delete(db_config)
    session.flush()
    if was_default:
        fallback = session.exec(
            select(ModelConfig)
            .where(
                ModelConfig.model_type == model_type,
                ModelConfig.is_active == True,  # noqa: E712
            )
            .order_by(ModelConfig.id.asc())
        ).first()
        if fallback:
            fallback.is_default = True
            session.add(fallback)
    session.commit()


def get_active_config(session: Session, model_type: str) -> Optional[ModelConfig]:
    """优先返回同类型「启用且默认」；否则退回任意启用配置（稳定按 id 升序）。"""
    preferred = session.exec(
        select(ModelConfig)
        .where(
            ModelConfig.model_type == model_type,
            ModelConfig.is_active == True,  # noqa: E712
            ModelConfig.is_default == True,  # noqa: E712
        )
        .order_by(ModelConfig.id.asc())
    ).first()
    if preferred:
        return preferred

    return session.exec(
        select(ModelConfig)
        .where(
            ModelConfig.model_type == model_type,
            ModelConfig.is_active == True,  # noqa: E712
        )
        .order_by(ModelConfig.id.asc())
    ).first()


def set_default_config(session: Session, config_id: int) -> ModelConfig:
    db_config = session.get(ModelConfig, config_id)
    if not db_config:
        raise ValueError("Config not found")
    db_config.is_active = True
    db_config.is_default = True
    _clear_other_defaults(session, db_config.model_type, keep_id=db_config.id)
    session.add(db_config)
    session.commit()
    session.refresh(db_config)
    return db_config
