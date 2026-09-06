"""Схема модулей 1-15 на момент стабилизационного спринта.

Первая миграция проекта. До неё схема создавалась вызовом `create_all()`, а он
умеет только создавать недостающие таблицы: добавить столбец в уже
существующую он не может, и при появлении новых полей база молча оставалась
старой.

**Существующая локальная база** этой ревизии уже соответствует. Применять её
к такой базе не нужно и нельзя - нужно пометить, что она применена:

    python -m alembic stamp 76201fab2384
    python -m alembic upgrade head

**Новая база** поднимается обычным способом:

    python -m alembic upgrade head

Revision ID: 76201fab2384
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '76201fab2384'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаёт всю схему модулей 1-15."""
    op.create_table('audit_batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('selection_criteria', sa.String(length=30), nullable=False),
    sa.Column('candidate_ids', sa.Text(), nullable=False),
    sa.Column('dispute_case_ids', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('calibration_constant_changes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('constant_ref', sa.String(length=120), nullable=False),
    sa.Column('previous_value', sa.String(length=200), nullable=False),
    sa.Column('new_value', sa.String(length=200), nullable=False),
    sa.Column('rationale_ru', sa.Text(), nullable=False),
    sa.Column('based_on_feedback_count', sa.Integer(), nullable=False),
    sa.Column('trust_accuracy_before', sa.Integer(), nullable=True),
    sa.Column('applied_by', sa.String(length=120), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('anomaly_flags',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('flag_type', sa.String(length=30), nullable=False),
    sa.Column('subject_evidence_or_answer_id', sa.String(length=60), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('anomaly_flags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_anomaly_flags_user_id'), ['user_id'], unique=False)

    op.create_table('competency_freshness',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('competency_id', sa.String(length=60), nullable=False),
    sa.Column('last_confirmed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('decay_countdown_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'competency_id', name='uq_freshness_user_competency')
    )
    with op.batch_alter_table('competency_freshness', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_competency_freshness_user_id'), ['user_id'], unique=False)

    op.create_table('decline_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('target_type', sa.String(length=20), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('decline_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_decline_records_user_id'), ['user_id'], unique=False)

    op.create_table('dispute_cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('explanation_id', sa.String(length=160), nullable=False),
    sa.Column('subject_type', sa.String(length=40), nullable=False),
    sa.Column('subject_id', sa.String(length=120), nullable=False),
    sa.Column('explanation_conclusion_ru', sa.Text(), nullable=False),
    sa.Column('explanation_evidence_refs', sa.Text(), nullable=False),
    sa.Column('origin', sa.String(length=30), nullable=False),
    sa.Column('candidate_statement', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('assigned_moderator', sa.String(length=120), nullable=True),
    sa.Column('info_request_ru', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dispute_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dispute_cases_user_id'), ['user_id'], unique=False)

    op.create_table('evidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('source_category', sa.String(length=20), nullable=True),
    sa.Column('url', sa.String(length=2048), nullable=True),
    sa.Column('file_ref', sa.String(length=255), nullable=True),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('nda', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('evidence', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_evidence_user_id'), ['user_id'], unique=False)

    op.create_table('export_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('format', sa.String(length=10), nullable=False),
    sa.Column('include_contacts', sa.Boolean(), nullable=False),
    sa.Column('prof_segment', sa.String(length=120), nullable=False),
    sa.Column('prof_level', sa.String(length=120), nullable=False),
    sa.Column('trust_score_version', sa.Integer(), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('export_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_export_requests_user_id'), ['user_id'], unique=False)

    op.create_table('prof_roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'level', name='uq_prof_role_user_level')
    )
    with op.batch_alter_table('prof_roles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prof_roles_user_id'), ['user_id'], unique=False)

    op.create_table('profile_growth_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('subject_ref', sa.String(length=120), nullable=False),
    sa.Column('from_value', sa.String(length=120), nullable=True),
    sa.Column('to_value', sa.String(length=120), nullable=True),
    sa.Column('description_ru', sa.Text(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('profile_growth_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_profile_growth_events_user_id'), ['user_id'], unique=False)

    op.create_table('raw_inputs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('raw_inputs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_raw_inputs_user_id'), ['user_id'], unique=False)

    op.create_table('recruiter_feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recruiter_user_id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.String(length=60), nullable=False),
    sa.Column('vacancy_id', sa.String(length=60), nullable=True),
    sa.Column('relevance_outcome', sa.String(length=30), nullable=False),
    sa.Column('trust_score_at_feedback', sa.Integer(), nullable=False),
    sa.Column('prof_score_at_feedback', sa.Integer(), nullable=False),
    sa.Column('free_text_comment', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['recruiter_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('recruiter_feedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recruiter_feedback_candidate_id'), ['candidate_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_recruiter_feedback_recruiter_user_id'), ['recruiter_user_id'], unique=False)

    op.create_table('return_triggers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('trigger_type', sa.String(length=40), nullable=False),
    sa.Column('related_ref', sa.String(length=120), nullable=False),
    sa.Column('match_score_at_detection', sa.Integer(), nullable=True),
    sa.Column('explanation_ref', sa.String(length=160), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acted_upon_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('return_triggers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_return_triggers_user_id'), ['user_id'], unique=False)

    op.create_table('reveal_states',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recruiter_user_id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.String(length=60), nullable=False),
    sa.Column('current_stage', sa.String(length=30), nullable=False),
    sa.Column('advance_trigger', sa.String(length=40), nullable=True),
    sa.Column('contact_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('candidate_contact_opt_in', sa.Boolean(), nullable=False),
    sa.Column('stage2_advanced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stage3_advanced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['recruiter_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('recruiter_user_id', 'candidate_id', name='uq_reveal_recruiter_candidate')
    )
    with op.batch_alter_table('reveal_states', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reveal_states_recruiter_user_id'), ['recruiter_user_id'], unique=False)

    op.create_table('search_contexts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('search_contexts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_search_contexts_user_id'), ['user_id'], unique=False)

    op.create_table('statements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('skill_name', sa.String(length=120), nullable=False),
    sa.Column('skill_name_ru', sa.String(length=120), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('source_of_claim', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'skill_name', name='uq_statement_user_skill')
    )
    with op.batch_alter_table('statements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_statements_user_id'), ['user_id'], unique=False)

    op.create_table('user_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_sessions_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_user_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('vacancy_checkpoints',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('vacancy_match_states',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('vacancy_id', sa.String(length=40), nullable=False),
    sa.Column('match_score', sa.Integer(), nullable=False),
    sa.Column('covered_requirement_ids', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'vacancy_id', name='uq_match_state_user_vacancy')
    )
    with op.batch_alter_table('vacancy_match_states', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vacancy_match_states_user_id'), ['user_id'], unique=False)

    op.create_table('verification_invites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recruiter_user_id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('note_ru', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['recruiter_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('verification_invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_verification_invites_recruiter_user_id'), ['recruiter_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_verification_invites_token'), ['token'], unique=True)

    op.create_table('visibility_states',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('consent_for_recruiter_view', sa.Boolean(), nullable=False),
    sa.Column('allow_immediate_identity_reveal', sa.Boolean(), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('component_feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('feedback_id', sa.Integer(), nullable=False),
    sa.Column('explanation_id', sa.String(length=160), nullable=False),
    sa.Column('subject_type', sa.String(length=40), nullable=False),
    sa.Column('subject_id', sa.String(length=120), nullable=False),
    sa.Column('verdict', sa.String(length=20), nullable=False),
    sa.Column('comment_ru', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['feedback_id'], ['recruiter_feedback.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('component_feedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_component_feedback_feedback_id'), ['feedback_id'], unique=False)

    op.create_table('contradiction_cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('statement_id', sa.Integer(), nullable=True),
    sa.Column('evidence_id', sa.Integer(), nullable=True),
    sa.Column('detected_by', sa.String(length=30), nullable=False),
    sa.Column('check_type', sa.String(length=30), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('detail_ru', sa.Text(), nullable=False),
    sa.Column('resolution_path', sa.String(length=20), nullable=True),
    sa.Column('explanation_text', sa.Text(), nullable=True),
    sa.Column('corrected_value', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('visibility_suspended', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['statement_id'], ['statements.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contradiction_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contradiction_cases_user_id'), ['user_id'], unique=False)

    op.create_table('dispute_history_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dispute_case_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=30), nullable=False),
    sa.Column('actor', sa.String(length=20), nullable=False),
    sa.Column('before_value', sa.Text(), nullable=True),
    sa.Column('after_value', sa.Text(), nullable=True),
    sa.Column('note_ru', sa.Text(), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['dispute_case_id'], ['dispute_cases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dispute_history_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dispute_history_entries_dispute_case_id'), ['dispute_case_id'], unique=False)

    op.create_table('nda_cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('competency_id', sa.String(length=60), nullable=False),
    sa.Column('statement_id', sa.Integer(), nullable=True),
    sa.Column('source_evidence_id', sa.Integer(), nullable=True),
    sa.Column('origin', sa.String(length=20), nullable=False),
    sa.Column('disclaimer_ack_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('suggested_method', sa.String(length=20), nullable=False),
    sa.Column('chosen_method', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['source_evidence_id'], ['evidence.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['statement_id'], ['statements.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('nda_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nda_cases_user_id'), ['user_id'], unique=False)

    op.create_table('probe_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('competency_id', sa.String(length=60), nullable=False),
    sa.Column('target_type', sa.String(length=20), nullable=False),
    sa.Column('artifact_evidence_id', sa.Integer(), nullable=True),
    sa.Column('template_id', sa.String(length=60), nullable=False),
    sa.Column('text_ru', sa.Text(), nullable=False),
    sa.Column('reason_ru', sa.Text(), nullable=False),
    sa.Column('grounded', sa.Boolean(), nullable=False),
    sa.Column('nda_abstract', sa.Boolean(), nullable=False),
    sa.Column('expected_terms', sa.Text(), nullable=False),
    sa.Column('follow_up_text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['artifact_evidence_id'], ['evidence.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('probe_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_probe_questions_user_id'), ['user_id'], unique=False)

    op.create_table('statement_evidence',
    sa.Column('statement_id', sa.Integer(), nullable=False),
    sa.Column('evidence_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['statement_id'], ['statements.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('statement_id', 'evidence_id')
    )
    op.create_table('trust_findings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('evidence_id', sa.Integer(), nullable=True),
    sa.Column('candidate_response', sa.String(length=30), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('trust_findings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_trust_findings_user_id'), ['user_id'], unique=False)

    op.create_table('moderator_overrides',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dispute_case_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('target_type', sa.String(length=40), nullable=False),
    sa.Column('target_id', sa.String(length=120), nullable=False),
    sa.Column('previous_value', sa.String(length=120), nullable=False),
    sa.Column('new_value', sa.String(length=120), nullable=False),
    sa.Column('rationale_ru', sa.Text(), nullable=False),
    sa.Column('history_entry_id', sa.Integer(), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['dispute_case_id'], ['dispute_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['history_entry_id'], ['dispute_history_entries.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('moderator_overrides', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_moderator_overrides_dispute_case_id'), ['dispute_case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_moderator_overrides_user_id'), ['user_id'], unique=False)

    op.create_table('nda_blind_witness_questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.String(length=60), nullable=False),
    sa.Column('prompt_ru', sa.Text(), nullable=False),
    sa.Column('reason_ru', sa.Text(), nullable=False),
    sa.Column('expected_terms', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('follow_up_ru', sa.Text(), nullable=True),
    sa.Column('follow_up_reason_ru', sa.Text(), nullable=True),
    sa.Column('follow_up_answer', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['nda_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('nda_blind_witness_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nda_blind_witness_questions_case_id'), ['case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_nda_blind_witness_questions_user_id'), ['user_id'], unique=False)

    op.create_table('nda_method_switches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('from_method', sa.String(length=20), nullable=True),
    sa.Column('to_method', sa.String(length=20), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['nda_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('nda_method_switches', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nda_method_switches_case_id'), ['case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_nda_method_switches_user_id'), ['user_id'], unique=False)

    op.create_table('nda_mirror_solutions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('scenario_id', sa.String(length=80), nullable=False),
    sa.Column('node_arrangement', sa.Text(), nullable=False),
    sa.Column('logic_explanation', sa.Text(), nullable=True),
    sa.Column('follow_up_ru', sa.Text(), nullable=True),
    sa.Column('follow_up_reason_ru', sa.Text(), nullable=True),
    sa.Column('follow_up_answer', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['nda_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('nda_mirror_solutions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nda_mirror_solutions_case_id'), ['case_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_nda_mirror_solutions_user_id'), ['user_id'], unique=False)

    op.create_table('probe_answers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('format', sa.String(length=20), nullable=False),
    sa.Column('typed_duration_ms', sa.Integer(), nullable=False),
    sa.Column('paste_attempts_blocked', sa.Integer(), nullable=False),
    sa.Column('keystroke_meta', sa.Text(), nullable=True),
    sa.Column('understanding_signal', sa.Boolean(), nullable=False),
    sa.Column('new_competency_signal', sa.Boolean(), nullable=False),
    sa.Column('evidence_id', sa.Integer(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['question_id'], ['probe_questions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('probe_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_probe_answers_question_id'), ['question_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_probe_answers_user_id'), ['user_id'], unique=False)

    op.create_table('probe_feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.String(length=60), nullable=False),
    sa.Column('reason', sa.String(length=40), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('screenshot_ref', sa.String(length=255), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['probe_questions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('probe_feedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_probe_feedback_question_id'), ['question_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_probe_feedback_user_id'), ['user_id'], unique=False)

    op.create_table('probe_follow_ups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('answer_id', sa.Integer(), nullable=False),
    sa.Column('trigger_reason', sa.String(length=20), nullable=False),
    sa.Column('text_ru', sa.Text(), nullable=False),
    sa.Column('reason_ru', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['answer_id'], ['probe_answers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('probe_follow_ups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_probe_follow_ups_answer_id'), ['answer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_probe_follow_ups_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    """Удаляет всю схему. В рабочей базе так делать не следует."""
    with op.batch_alter_table('probe_follow_ups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_probe_follow_ups_user_id'))
        batch_op.drop_index(batch_op.f('ix_probe_follow_ups_answer_id'))

    op.drop_table('probe_follow_ups')
    with op.batch_alter_table('probe_feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_probe_feedback_user_id'))
        batch_op.drop_index(batch_op.f('ix_probe_feedback_question_id'))

    op.drop_table('probe_feedback')
    with op.batch_alter_table('probe_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_probe_answers_user_id'))
        batch_op.drop_index(batch_op.f('ix_probe_answers_question_id'))

    op.drop_table('probe_answers')
    with op.batch_alter_table('nda_mirror_solutions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nda_mirror_solutions_user_id'))
        batch_op.drop_index(batch_op.f('ix_nda_mirror_solutions_case_id'))

    op.drop_table('nda_mirror_solutions')
    with op.batch_alter_table('nda_method_switches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nda_method_switches_user_id'))
        batch_op.drop_index(batch_op.f('ix_nda_method_switches_case_id'))

    op.drop_table('nda_method_switches')
    with op.batch_alter_table('nda_blind_witness_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nda_blind_witness_questions_user_id'))
        batch_op.drop_index(batch_op.f('ix_nda_blind_witness_questions_case_id'))

    op.drop_table('nda_blind_witness_questions')
    with op.batch_alter_table('moderator_overrides', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_moderator_overrides_user_id'))
        batch_op.drop_index(batch_op.f('ix_moderator_overrides_dispute_case_id'))

    op.drop_table('moderator_overrides')
    with op.batch_alter_table('trust_findings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_trust_findings_user_id'))

    op.drop_table('trust_findings')
    op.drop_table('statement_evidence')
    with op.batch_alter_table('probe_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_probe_questions_user_id'))

    op.drop_table('probe_questions')
    with op.batch_alter_table('nda_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nda_cases_user_id'))

    op.drop_table('nda_cases')
    with op.batch_alter_table('dispute_history_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dispute_history_entries_dispute_case_id'))

    op.drop_table('dispute_history_entries')
    with op.batch_alter_table('contradiction_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contradiction_cases_user_id'))

    op.drop_table('contradiction_cases')
    with op.batch_alter_table('component_feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_component_feedback_feedback_id'))

    op.drop_table('component_feedback')
    op.drop_table('visibility_states')
    with op.batch_alter_table('verification_invites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_verification_invites_token'))
        batch_op.drop_index(batch_op.f('ix_verification_invites_recruiter_user_id'))

    op.drop_table('verification_invites')
    with op.batch_alter_table('vacancy_match_states', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_vacancy_match_states_user_id'))

    op.drop_table('vacancy_match_states')
    op.drop_table('vacancy_checkpoints')
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_user_sessions_token_hash'))

    op.drop_table('user_sessions')
    with op.batch_alter_table('statements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_statements_user_id'))

    op.drop_table('statements')
    with op.batch_alter_table('search_contexts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_search_contexts_user_id'))

    op.drop_table('search_contexts')
    with op.batch_alter_table('reveal_states', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reveal_states_recruiter_user_id'))

    op.drop_table('reveal_states')
    with op.batch_alter_table('return_triggers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_return_triggers_user_id'))

    op.drop_table('return_triggers')
    with op.batch_alter_table('recruiter_feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recruiter_feedback_recruiter_user_id'))
        batch_op.drop_index(batch_op.f('ix_recruiter_feedback_candidate_id'))

    op.drop_table('recruiter_feedback')
    with op.batch_alter_table('raw_inputs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_raw_inputs_user_id'))

    op.drop_table('raw_inputs')
    with op.batch_alter_table('profile_growth_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_profile_growth_events_user_id'))

    op.drop_table('profile_growth_events')
    with op.batch_alter_table('prof_roles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_prof_roles_user_id'))

    op.drop_table('prof_roles')
    with op.batch_alter_table('export_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_export_requests_user_id'))

    op.drop_table('export_requests')
    with op.batch_alter_table('evidence', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evidence_user_id'))

    op.drop_table('evidence')
    with op.batch_alter_table('dispute_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dispute_cases_user_id'))

    op.drop_table('dispute_cases')
    with op.batch_alter_table('decline_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_decline_records_user_id'))

    op.drop_table('decline_records')
    with op.batch_alter_table('competency_freshness', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_competency_freshness_user_id'))

    op.drop_table('competency_freshness')
    with op.batch_alter_table('anomaly_flags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_anomaly_flags_user_id'))

    op.drop_table('anomaly_flags')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('calibration_constant_changes')
    op.drop_table('audit_batches')
