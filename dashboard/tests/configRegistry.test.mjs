import test from 'node:test';
import assert from 'node:assert/strict';

const { normalizeConfigMetadata } = await import('../src/composables/useConfigRegistry.ts');

const metadata = {
  ai_group: {
    name: 'ai_group.name',
    metadata: {
      agent_runner: {
        description: 'ai_group.agent_runner.description',
        type: 'object',
        items: {},
      },
      persona: {
        description: 'ai_group.persona.description',
        type: 'object',
        items: {},
      },
      knowledgebase: {
        description: 'ai_group.knowledgebase.description',
        type: 'object',
        items: {},
      },
      custom_extension: {
        description: 'ai_group.custom_extension.description',
        type: 'object',
        items: {},
      },
    },
  },
  platform_group: {
    name: 'platform_group.name',
    metadata: {
      general: {
        description: 'platform_group.general.description',
        type: 'object',
        items: {},
      },
    },
  },
  ext_group: {
    name: 'ext_group.name',
    metadata: {
      segmented_reply: {
        description: 'ext_group.segmented_reply.description',
        type: 'object',
        items: {},
      },
      ltm: {
        description: 'ext_group.ltm.description',
        type: 'object',
        items: {},
      },
    },
  },
  interaction_middleware_group: {
    name: 'interaction_middleware_group.name',
    metadata: {
      expression: {
        description: 'interaction_middleware_group.expression.description',
        type: 'object',
        items: {},
      },
      planner: {
        description: 'interaction_middleware_group.planner.description',
        type: 'object',
        items: {},
      },
      personal_policy: {
        description: 'interaction_middleware_group.personal_policy.description',
        type: 'object',
        items: {},
      },
    },
  },
};

test('normalizeConfigMetadata projects mapped ai sections into their workspaces', () => {
  const normalized = normalizeConfigMetadata(metadata, 'normal');

  assert.deepEqual(Object.keys(normalized), [
    'ai_group__persona',
    'ai_group__agent_runner',
    'ai_group__custom_extension',
    'interaction_middleware_group__expression',
    'interaction_middleware_group__planner',
    'interaction_middleware_group__personal_policy',
    'platform_group',
    'ai_group__knowledgebase',
  ]);
  assert.deepEqual(normalized.ai_group__persona, {
    key: 'ai_group__persona',
    name: 'ai_group.persona.description',
    metadata: { persona: metadata.ai_group.metadata.persona },
    workspace: 'persona',
    scope: 'persona',
    order: 10,
    legacyGroup: 'ai_group',
    legacySection: 'persona',
  });
  assert.equal(normalized.ai_group__custom_extension.workspace, 'intelligence');
  assert.equal(normalized.ai_group__custom_extension.legacySection, 'custom_extension');
  assert.deepEqual(normalized.platform_group.metadata, metadata.platform_group.metadata);
  assert.equal(normalized.ext_group__ltm, undefined);
});

test('normalizeConfigMetadata keeps only extension groups for extension configuration', () => {
  const normalized = normalizeConfigMetadata(metadata, 'extension');

  assert.deepEqual(Object.keys(normalized), [
    'ext_group__segmented_reply',
    'ext_group__ltm',
  ]);
  assert.equal(normalized.ext_group__ltm.workspace, 'operations');
  assert.equal(normalized.ext_group__segmented_reply.workspace, 'operations');
});

test('normalizeConfigMetadata keeps non-model interaction sections in extension configuration', () => {
  const normalized = normalizeConfigMetadata({
    interaction_middleware_group: {
      name: 'interaction_middleware_group.name',
      metadata: {
        general: { description: 'interaction_middleware_group.general.description' },
        plugin: { description: 'interaction_middleware_group.plugin.description' },
        context: { description: 'interaction_middleware_group.context.description' },
        expression: metadata.interaction_middleware_group.metadata.expression,
        planner: metadata.interaction_middleware_group.metadata.planner,
        personal_policy: metadata.interaction_middleware_group.metadata.personal_policy,
        personal_runtime_policy: { description: 'interaction_middleware_group.personal_runtime_policy.description' },
        progress: { description: 'interaction_middleware_group.progress.description' },
        future_section: { description: 'interaction_middleware_group.future_section.description' },
      },
    },
    memory_group: {
      name: 'memory_group.name',
      metadata: {
        general: { description: 'memory_group.general.description' },
      },
    },
  }, 'extension');

  assert.equal(normalized.interaction_middleware_group__general.workspace, 'operations');
  assert.equal(normalized.interaction_middleware_group__plugin.workspace, 'operations');
  assert.equal(normalized.interaction_middleware_group__context.workspace, 'operations');
  assert.equal(normalized.interaction_middleware_group__personal_runtime_policy.workspace, 'operations');
  assert.equal(normalized.interaction_middleware_group__progress.workspace, 'operations');
  assert.equal(normalized.interaction_middleware_group__future_section.workspace, 'operations');
  assert.equal(normalized.interaction_middleware_group__expression, undefined);
  assert.equal(normalized.interaction_middleware_group__planner, undefined);
  assert.equal(normalized.interaction_middleware_group__personal_policy, undefined);
  assert.equal(normalized.memory_group.workspace, 'operations');

  const unknownOnly = normalizeConfigMetadata({
    interaction_middleware_group: {
      name: 'interaction_middleware_group.name',
      metadata: {
        future_section: { description: 'interaction_middleware_group.future_section.description' },
      },
    },
  }, 'extension');
  assert.equal(unknownOnly.interaction_middleware_group.workspace, 'operations');
});

test('normal config places interaction model routing in intelligence workspace', () => {
  const normalized = normalizeConfigMetadata(metadata, 'normal');
  for (const section of ['expression', 'planner', 'personal_policy']) {
    const entry = normalized[`interaction_middleware_group__${section}`];
    assert.equal(entry.workspace, 'intelligence');
    assert.equal(entry.scope, 'profile');
  }
});
