// @ts-check
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import importX from 'eslint-plugin-import-x';

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    ignores: ['**/dist/**', '**/node_modules/**', '**/*.config.js'],
  },
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { 'import-x': importX },
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      'import-x/order': [
        'warn',
        {
          groups: ['builtin', 'external', 'internal', ['parent', 'sibling', 'index']],
          'newlines-between': 'always',
        },
      ],
    },
  },
  {
    // ADR-0001 / 02 §1.1 — contracts depends on nothing but zod.
    files: ['packages/contracts/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@grace/*'],
              message: 'packages/contracts depends on nothing except zod (ADR-0001, doc 02 §1.1).',
            },
          ],
        },
      ],
    },
  },
  {
    // platform/vapi/tools/*.json is generated FROM packages/contracts — never hand-edited (ADR-0010).
    // Enforced by CI drift check (platform:vapi:diff), not by lint, since it's JSON not TS.
    files: ['platform/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@grace/adapters/*', '@grace/db/*'],
              message:
                'platform/ is config-as-code for Vapi and n8n only (ADR-0010). It has no business logic and no DB access.',
            },
          ],
        },
      ],
    },
  },
);
