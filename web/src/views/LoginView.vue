<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { login, register } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { safeRedirect } from '@/utils/redirect'

type Mode = 'login' | 'register'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const mode = ref<Mode>('login')
const loading = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
  nickname: '',
  grade: '',
})

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^\S{3,50}$/,
      message: '用户名 3–50 个字符，不能含空格',
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码 8–128 个字符', trigger: 'blur' },
  ],
  nickname: [
    { required: true, message: '请输入昵称', trigger: 'blur' },
    { max: 50, message: '昵称不超过 50 字', trigger: 'blur' },
  ],
  grade: [{ max: 20, message: '年级不超过 20 字', trigger: 'blur' }],
}

const submitLabel = computed(() => (mode.value === 'login' ? '登录' : '注册并登录'))

function switchMode(next: Mode): void {
  if (mode.value === next) return
  mode.value = next
  formRef.value?.clearValidate()
}

async function onSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    if (mode.value === 'register') {
      await register({
        username: form.username.trim(),
        password: form.password,
        nickname: form.nickname.trim(),
        grade: form.grade.trim() || undefined,
      })
      ElMessage.success('注册成功，正在登录')
    }
    const session = await login({
      username: form.username.trim(),
      password: form.password,
    })
    auth.setSession(session.access_token, session.user)
    ElMessage.success('欢迎回来')
    await router.replace(safeRedirect(route.query.redirect))
  } catch {
    if (mode.value === 'register') mode.value = 'login'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="brand-panel">
      <div class="brand-mark">知序</div>
      <h1>把笔记、错题和知识点<br />连成一张可复习的网</h1>
      <p class="brand-lead">面向高中生的个性化学习工作台</p>
      <ul class="brand-points">
        <li><span>01</span>可溯源问答，每个结论都能点回原文</li>
        <li><span>02</span>笔记自动对齐已有知识点，不生造节点</li>
        <li><span>03</span>错题诊断与复习计划，按掌握度推进</li>
      </ul>
      <p class="brand-foot">Study Agent · 毕业设计演示版</p>
    </section>

    <section class="form-panel">
      <div class="form-card">
        <div class="tabs" role="tablist" aria-label="登录或注册">
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'login'"
            :class="{ active: mode === 'login' }"
            @click="switchMode('login')"
          >
            登录
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mode === 'register'"
            :class="{ active: mode === 'register' }"
            @click="switchMode('register')"
          >
            注册
          </button>
        </div>

        <h2>{{ mode === 'login' ? '欢迎回来' : '创建学生账号' }}</h2>
        <p class="form-hint">
          {{ mode === 'login' ? '继续你的学习记录' : '注册后自动登录，进入学习工作台' }}
        </p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="onSubmit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              name="username"
              autocomplete="username"
              placeholder="3–50 个字符，不能含空格"
              autofocus
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              name="password"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="至少 8 个字符"
            />
          </el-form-item>
          <template v-if="mode === 'register'">
            <el-form-item label="昵称" prop="nickname">
              <el-input v-model="form.nickname" name="nickname" placeholder="展示用昵称" />
            </el-form-item>
            <el-form-item label="年级（可选）" prop="grade">
              <el-input v-model="form.grade" name="grade" placeholder="如：高一" />
            </el-form-item>
          </template>

          <el-button
            class="login-submit"
            type="primary"
            native-type="submit"
            :loading="loading"
          >
            {{ submitLabel }}
          </el-button>
        </el-form>

        <p class="form-switch">
          {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
          <button type="button" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ mode === 'login' ? '注册学生账号' : '去登录' }}
          </button>
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(420px, 46%) 1fr;
  min-height: 100vh;
  background: var(--app-bg);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 64px 72px;
  background:
    radial-gradient(circle at 18% 12%, rgba(59, 91, 219, 0.12), transparent 42%),
    linear-gradient(160deg, #f2f4ff 0%, #f7f8fa 60%);
  border-right: 1px solid var(--app-border);
}

.brand-mark {
  width: fit-content;
  margin-bottom: 48px;
  padding: 6px 14px;
  border: 1px solid var(--app-primary);
  border-radius: 999px;
  color: var(--app-primary);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.12em;
}

.brand-panel h1 {
  margin: 0 0 16px;
  font-size: 34px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: -0.01em;
}

.brand-lead {
  margin: 0 0 40px;
  color: var(--app-text-secondary);
  font-size: 15px;
}

.brand-points {
  display: grid;
  gap: 16px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--app-text-secondary);
}

.brand-points li {
  display: flex;
  gap: 12px;
  align-items: baseline;
}

.brand-points span {
  color: var(--app-primary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.08em;
}

.brand-foot {
  margin: 64px 0 0;
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.form-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
}

.form-card {
  width: 380px;
  padding: 32px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
}

.tabs {
  display: flex;
  gap: 24px;
  margin-bottom: 28px;
  border-bottom: 1px solid var(--app-border);
}

.tabs button {
  position: relative;
  padding: 0 0 10px;
  background: none;
  border: none;
  color: var(--app-text-secondary);
  font: inherit;
  cursor: pointer;
}

.tabs button.active {
  color: var(--app-primary);
  font-weight: 600;
}

.tabs button.active::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  background: var(--app-primary);
  content: '';
}

.form-card h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
}

.form-hint {
  margin: 0 0 24px;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.login-submit {
  width: 100%;
  margin-top: 8px;
}

.form-switch {
  margin: 20px 0 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  text-align: center;
}

.form-switch button {
  padding: 0;
  background: none;
  border: none;
  color: var(--app-primary);
  font: inherit;
  cursor: pointer;
}
</style>