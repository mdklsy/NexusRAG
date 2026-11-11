import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { ApiOutlined, KeyOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useState } from "react";

interface AppRow {
  id: string;
  name: string;
  description: string;
  icon: string;
  system_prompt: string;
  llm_config: any;
  retrieval_config: any;
  is_active: boolean;
  kb_ids?: string[];
}

const ICONS = ["🤖", "💬", "📚", "🛎️", "🎯", "💡", "⚖️", "🏥", "🏢", "🛒"];

function ConfigForm({
  form,
  kbs,
}: {
  form: any;
  kbs: { id: string; name: string }[];
}) {
  const kgOn = Form.useWatch(["retrieval_config", "use_kg"], form);
  const rerank = Form.useWatch(["retrieval_config", "rerank"], form);
  return (
    <Form form={form} layout="vertical" initialValues={{ temperature: 0.3, max_tokens: 2048, top_k: 5, score_threshold: 0.35, use_kg: true, kg_hops: 1, kg_top_entities: 3, history_window: 6, intent_route: true, use_bm25: true, rerank: "none", model: "" }}>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="name" label="应用名称" rules={[{ required: true }]}>
            <Input placeholder="如：智能客服" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="kb_ids" label="绑定知识库">
            <Select mode="multiple" placeholder="可多选" options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="description" label="描述">
        <Input />
      </Form.Item>
      <Form.Item name="system_prompt" label="系统提示词（人设与规则）">
        <Input.TextArea
          rows={3}
          placeholder="你是 XX 公司的智能客服，语气专业友好…"
        />
      </Form.Item>
      <Typography.Title level={5}>模型（留空 = 使用全局配置）</Typography.Title>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={["llm_config", "model"]} label="模型名">
            <Input placeholder="deepseek-chat" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={["llm_config", "temperature"]} label="Temperature">
            <InputNumber min={0} max={2} step={0.1} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={["llm_config", "max_tokens"]} label="Max Tokens">
            <InputNumber min={128} max={16384} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name={["llm_config", "api_base"]}
            label="API Base（应用专属厂商）"
            extra="例：https://api.deepseek.com/v1、智谱、通义、Ollama…"
          >
            <Input placeholder="留空用全局 LLM_API_BASE" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name={["llm_config", "api_key"]}
            label="API Key"
            extra="应用专属密钥，AES 加密存储；留空 = 沿用已保存/全局配置"
          >
            <Input.Password placeholder="留空 = 沿用已保存 / 全局 Key" />
          </Form.Item>
        </Col>
      </Row>
      <Typography.Title level={5} style={{ marginBottom: 4 }}>
        检索策略
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0, fontSize: 12 }}>
        控制「怎么从知识库找资料、找多少、怎么排序」
      </Typography.Paragraph>
      <Row gutter={16}>
        <Col span={6}>
          <Form.Item
            name={["retrieval_config", "top_k"]}
            label="召回条数 Top K"
            tooltip="检索时返回的最相关片段数量，作为参考资料送给模型。越大信息越全，但更慢、且可能引入无关内容。"
            extra={<span style={{ fontSize: 12 }}>送给模型的参考片段条数</span>}
          >
            <InputNumber min={1} max={20} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item
            name={["retrieval_config", "score_threshold"]}
            label="相似度阈值"
            tooltip="0~1：相关度低于该值的片段直接丢弃，宁缺毋滥。检索不到资料时助手会如实说「没找到」。"
            extra={<span style={{ fontSize: 12 }}>低分丢弃；留空 = 不过滤</span>}
          >
            <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item
            name={["retrieval_config", "history_window"]}
            label="历史轮数"
            tooltip="多轮对话时携带最近几条历史消息（一轮=一问一答），让「它」「刚才说的」这类指代能被理解。"
            extra={<span style={{ fontSize: 12 }}>多轮对话的上下文条数</span>}
          >
            <InputNumber min={0} max={20} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item
            name={["retrieval_config", "intent_route"]}
            label="意图路由"
            tooltip="先由模型判断提问类型：「知识问答」走检索，「你好/谢谢」等闲聊直接回复。"
            extra={<span style={{ fontSize: 12 }}>闲聊直答，省 token</span>}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item
        name={["retrieval_config", "use_bm25"]}
        label="BM25 混合检索"
        tooltip="关键词倒排检索与语义向量并行召回、RRF 融合排序。型号、专有名词等精确词，BM25 比向量更准。"
        extra={<span style={{ fontSize: 12 }}>关闭 = 只用语义向量检索</span>}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name={["retrieval_config", "use_kg"]}
        label="知识图谱增强"
        tooltip="从文档预抽取的实体关系图中补充关联事实，如「NexusRAG --使用--> Qdrant」帮助回答跨实体问题。"
        extra={<span style={{ fontSize: 12 }}>开启后可设置下方跳数与实体上限</span>}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      {kgOn && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Form.Item
              name={["retrieval_config", "kg_hops"]}
              label="图谱跳数"
              tooltip="从问题命中的实体出发，沿关系边扩展几层（1~3）。例如「Qdrant」1 跳就能到「向量数据库」。"
              extra={<span style={{ fontSize: 12 }}>关系扩展层数 1~3</span>}
            >
              <InputNumber min={1} max={3} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name={["retrieval_config", "kg_top_entities"]}
              label="实体上限"
              tooltip="最多注入多少条图谱事实到提示词，防止图谱内容挤占正文空间。"
              extra={<span style={{ fontSize: 12 }}>注入的事实条数上限</span>}
            >
              <InputNumber min={1} max={10} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
      )}
      <Form.Item
        name={["retrieval_config", "rerank"]}
        label="重排"
        tooltip="向量+BM25 融合召回后，对候选片段做相关性二次精排，把最相关的排到最前。"
        extra={<span style={{ fontSize: 12 }}>推荐托管 API 重排：快、便宜、效果稳定</span>}
      >
        <Select
          style={{ width: 280 }}
          options={[
            { value: "none", label: "不重排" },
            { value: "api", label: "托管 API 重排（推荐）" },
            { value: "llm", label: "LLM 重排（让对话模型打分）" },
            { value: "cross_encoder", label: "本地 Cross-Encoder（需装依赖）" },
          ]}
        />
      </Form.Item>
      {rerank === "api" && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="托管重排使用全局配置，应用内无需填写"
          description="在部署目录 .env 中配置 RERANK_API_BASE / RERANK_API_KEY / RERANK_MODEL（默认 BAAI/bge-reranker-v2-m3，硅基流动免费档）。"
        />
      )}
      {rerank === "cross_encoder" && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="本地 Cross-Encoder 需要在 backend 安装可选依赖"
          description="pip install '.[rerank]'（会拉起 sentence-transformers，较重）；轻量部署建议用托管 API 重排。"
        />
      )}
      {rerank === "llm" && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="LLM 重排由当前对话模型给候选打分"
          description="无需额外配置，但每轮多一次模型调用，速度稍慢。"
        />
      )}

      <Typography.Title level={5} style={{ marginBottom: 4 }}>
        网页挂件
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0, fontSize: 12 }}>
        嵌入到外部网站的客服挂件（网页引入一行 widget.js 脚本），此处配置其外观
      </Typography.Paragraph>
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item
            name={["widget_config", "title"]}
            label="挂件标题"
            extra={<span style={{ fontSize: 12 }}>聊天窗口顶部标题</span>}
          >
            <Input placeholder="智能客服" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item
            name={["widget_config", "theme"]}
            label="主题色"
            tooltip="挂件按钮与气泡的主色调"
            extra={<span style={{ fontSize: 12 }}>#hex，如 #1677ff</span>}
          >
            <Input placeholder="#1677ff" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item
            name={["widget_config", "bubble"]}
            label="按钮图标"
            extra={<span style={{ fontSize: 12 }}>悬浮球 emoji</span>}
          >
            <Input placeholder="💬" />
          </Form.Item>
        </Col>
        <Col span={24}>
          <Form.Item
            name={["widget_config", "welcome"]}
            label="欢迎语"
            extra={<span style={{ fontSize: 12 }}>用户打开挂件时先展示的一句话</span>}
          >
            <Input placeholder="你好，请问有什么可以帮你？" />
          </Form.Item>
        </Col>
      </Row>
    </Form>
  );
}

/** 业务工具（连接器）管理：编辑抽屉内使用 */
function ToolsSection({ appId }: { appId: string }) {
  const qc = useQueryClient();
  const [editingTool, setEditingTool] = useState<any | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const { data: tools } = useQuery({
    queryKey: ["tools", appId],
    queryFn: () => api.get<any[]>(`/api/v1/apps/${appId}/tools`),
  });

  const save = useMutation({
    mutationFn: (values: any) => {
      const { id, ...rest } = values;
      return id
        ? api.put(`/api/v1/apps/${appId}/tools/${id}`, rest)
        : api.post(`/api/v1/apps/${appId}/tools`, rest);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tools", appId] });
      setEditingTool(null);
      setCreating(false);
      message.success("工具已保存");
    },
    onError: (e: any) => message.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/apps/${appId}/tools/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools", appId] }),
  });

  const openForm = (tool?: any) => {
    form.resetFields();
    if (tool) {
      setEditingTool(tool);
      form.setFieldsValue({ ...tool, config: tool.config });
    } else {
      setCreating(true);
      form.setFieldValue("type", "http_api");
    }
  };

  return (
    <>
      <Typography.Title level={5}>
        业务工具（LLM 可调用你的业务系统）
      </Typography.Title>
      <Table
        rowKey="id"
        size="small"
        dataSource={tools || []}
        pagination={false}
        locale={{ emptyText: "未配置工具。添加 HTTP API 或只读 SQL 查询，让助手能查业务数据。" }}
        columns={[
          { title: "名称", dataIndex: "name" },
          {
            title: "类型",
            dataIndex: "type",
            width: 90,
            render: (v) => <Tag>{v === "http_api" ? "HTTP API" : "SQL 只读"}</Tag>,
          },
          { title: "说明", dataIndex: "description", ellipsis: true },
          {
            title: "状态",
            dataIndex: "enabled",
            width: 70,
            render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
          },
          {
            title: "",
            width: 120,
            render: (_, r) => (
              <Space>
                <Button size="small" onClick={() => openForm(r)}>
                  编辑
                </Button>
                <Popconfirm title="删除该工具？" onConfirm={() => remove.mutate(r.id)}>
                  <Button size="small" danger type="text">
                    删
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
        footer={() => (
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => openForm()}>
            添加工具
          </Button>
        )}
      />

      <Modal
        title={editingTool ? `编辑工具 - ${editingTool.name}` : "添加业务工具"}
        open={creating || !!editingTool}
        onCancel={() => {
          setEditingTool(null);
          setCreating(false);
        }}
        onOk={() => form.validateFields().then((v) => save.mutate(v))}
        confirmLoading={save.isPending}
        width={560}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="id" hidden>
            <Input />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="name"
                label="函数名（英文）"
                rules={[{ required: true, pattern: /^[a-zA-Z][a-zA-Z0-9_]*$/, message: "字母开头的英文/数字/下划线" }]}
              >
                <Input disabled={!!editingTool} placeholder="query_order" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="type" label="类型" rules={[{ required: true }]}>
                <Select
                  disabled={!!editingTool}
                  options={[
                    { value: "http_api", label: "HTTP API（推荐）" },
                    { value: "sql_db", label: "SQL 只读查询" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="description" label="用途说明（给 LLM 看，写清楚何时调用、参数含义）">
            <Input.TextArea
              rows={2}
              placeholder="查询订单状态。参数：order_id=订单号。用于用户询问订单进度时。"
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.type !== b.type}>
            {({ getFieldValue }) =>
              getFieldValue("type") === "sql_db" ? (
                <Form.Item
                  name={["config", "dsn"]}
                  label="数据库连接串（仅 SELECT 权限账号）"
                  rules={[{ required: true }]}
                >
                  <Input placeholder="mysql+pymysql://readonly:pwd@host:3306/db" />
                </Form.Item>
              ) : (
                <>
                  <Row gutter={12}>
                    <Col span={6}>
                      <Form.Item name={["config", "method"]} label="方法" initialValue="GET">
                        <Select
                          options={["GET", "POST", "PUT", "DELETE"].map((m) => ({
                            value: m,
                            label: m,
                          }))}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={18}>
                      <Form.Item
                        name={["config", "url"]}
                        label="接口 URL（路径参数用 {order_id} 占位）"
                        rules={[{ required: true }]}
                      >
                        <Input placeholder="https://api.example.com/orders/{order_id}" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item name={["config", "headers"]} label="请求头 JSON（鉴权等）">
                    <Input.TextArea
                      rows={2}
                      placeholder='{"Authorization": "Bearer xxx"}'
                    />
                  </Form.Item>
                </>
              )
            }
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default function Apps() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<AppRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();
  const [keyApp, setKeyApp] = useState<AppRow | null>(null);
  const [newKey, setNewKey] = useState<string | null>(null);

  const { data: apps } = useQuery({
    queryKey: ["apps"],
    queryFn: () => api.get<AppRow[]>("/api/v1/apps"),
  });
  const { data: kbs } = useQuery({
    queryKey: ["kbs"],
    queryFn: () => api.get<any[]>("/api/v1/kbs"),
  });
  const { data: apiKeys } = useQuery({
    queryKey: ["apiKeys", keyApp?.id],
    queryFn: () => api.get<any[]>(`/api/v1/apps/${keyApp!.id}/api-keys`),
    enabled: !!keyApp,
  });

  const save = useMutation({
    mutationFn: (values: any) =>
      editing
        ? api.put(`/api/v1/apps/${editing.id}`, values)
        : api.post("/api/v1/apps", values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["apps"] });
      setEditing(null);
      setCreating(false);
      message.success("已保存");
    },
    onError: (e: any) => message.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/apps/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["apps"] });
      message.success("已删除");
    },
  });

  const createKey = useMutation({
    mutationFn: (scope: string) =>
      api.post<any>(`/api/v1/apps/${keyApp!.id}/api-keys?name=${scope === "chat" ? "widget" : "console"}&scope=${scope}`),
    onSuccess: (data) => {
      setNewKey(data.key);
      qc.invalidateQueries({ queryKey: ["apiKeys", keyApp?.id] });
    },
    onError: (e: any) => message.error(e.message),
  });

  const openEdit = async (app: AppRow) => {
    const detail = await api.get<AppRow>(`/api/v1/apps/${app.id}`);
    setEditing(detail);
    // 旧数据可能缺某个检索参数：与默认值合并，避免表单显示空、保存时丢字段
    const rc = { top_k: 5, use_kg: true, kg_hops: 1, kg_top_entities: 3, history_window: 6, intent_route: true, use_bm25: true, rerank: "none", ...(detail.retrieval_config || {}) };
    form.setFieldsValue({
      ...detail,
      retrieval_config: rc,
    });
    form.setFieldValue(["llm_config", "model"], detail.llm_config?.model || "");
    form.setFieldValue(["llm_config", "temperature"], detail.llm_config?.temperature ?? 0.3);
    form.setFieldValue(["llm_config", "max_tokens"], detail.llm_config?.max_tokens ?? 2048);
  };

  return (
    <Card
      title="应用"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            setCreating(true);
          }}
        >
          创建应用
        </Button>
      }
    >
      <Table<AppRow>
        rowKey="id"
        dataSource={apps}
        locale={{ emptyText: <Empty description="创建一个应用开始（如：智能客服）" /> }}
        columns={[
          {
            title: "应用",
            render: (_, r) => (
              <Space>
                <span style={{ fontSize: 20 }}>{r.icon}</span>
                <div>
                  <div>{r.name}</div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {r.description}
                  </Typography.Text>
                </div>
              </Space>
            ),
          },
          {
            title: "知识库",
            render: (_, r) => {
              const names = (r.kb_ids || []).map(
                (id) => (kbs || []).find((k) => k.id === id)?.name
              );
              return names.length ? names.join("、") : <Tag>未绑定</Tag>;
            },
          },
          {
            title: "图谱",
            render: (_, r) => (r.retrieval_config?.use_kg ? <Tag color="blue">KG 增强</Tag> : <Tag>关闭</Tag>),
          },
          {
            title: "状态",
            dataIndex: "is_active",
            width: 80,
            render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
          },
          {
            title: "操作",
            width: 240,
            render: (_, r) => (
              <Space>
                <Button size="small" onClick={() => openEdit(r)}>
                  配置
                </Button>
                <Button size="small" icon={<KeyOutlined />} onClick={() => { setKeyApp(r); setNewKey(null); }}>
                  API Key
                </Button>
                <Popconfirm title="删除应用？" onConfirm={() => remove.mutate(r.id)}>
                  <Button size="small" danger type="text">
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={editing ? `配置 - ${editing.name}` : "创建应用"}
        open={creating || !!editing}
        width={780}
        onCancel={() => {
          setEditing(null);
          setCreating(false);
        }}
        footer={[
          <Button
            key="cancel"
            onClick={() => {
              setEditing(null);
              setCreating(false);
            }}
          >
            取消
          </Button>,
          <Button
            key="save"
            type="primary"
            onClick={async () => {
              const values = await form.validateFields();
              save.mutate(values);
            }}
            loading={save.isPending}
          >
            保存
          </Button>,
        ]}
      >
        <ConfigForm form={form} kbs={kbs || []} />
        {editing && (
          <div style={{ marginTop: 24 }}>
            <ToolsSection appId={editing.id} />
          </div>
        )}
      </Modal>

      <Modal
        title={`API Keys - ${keyApp?.name || ""}`}
        open={!!keyApp}
        onCancel={() => setKeyApp(null)}
        footer={null}
        width={640}
      >
        {newKey && (
          <Typography.Paragraph copyable style={{ marginBottom: 16 }}>
            <Tooltip title="仅显示一次，请立即保存">
              <Tag color="orange">新 Key（仅此一次可见）</Tag>
            </Tooltip>
            {newKey}
          </Typography.Paragraph>
        )}
        <Table
          rowKey="id"
          size="small"
          dataSource={apiKeys}
          pagination={false}
          columns={[
            { title: "名称", dataIndex: "name" },
            { title: "权限", dataIndex: "scope", width: 90, render: (v) => (v === "chat" ? <Tag color="blue">仅对话</Tag> : <Tag>完整</Tag>) },
            { title: "创建时间", dataIndex: "created_at", render: (v) => v?.slice(0, 10) },
            {
              title: "",
              width: 60,
              render: (_, r: any) => (
                <Popconfirm
                  title="删除该 Key？"
                  onConfirm={async () => {
                    await api.del(`/api/v1/apps/${keyApp!.id}/api-keys/${r.id}`);
                    qc.invalidateQueries({ queryKey: ["apiKeys", keyApp?.id] });
                  }}
                >
                  <Button size="small" danger type="text">
                    删
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
        <Space style={{ marginTop: 12, width: "100%" }}>
          <Button
            type="dashed"
            icon={<ApiOutlined />}
            onClick={() => createKey.mutate("full")}
            loading={createKey.isPending}
          >
            生成完整 Key
          </Button>
          <Button
            type="dashed"
            onClick={() => createKey.mutate("chat")}
            loading={createKey.isPending}
          >
            生成挂件 Key（仅对话）
          </Button>
        </Space>
        {newKey && (
          <div style={{ marginTop: 16 }}>
            <Typography.Text strong style={{ fontSize: 12 }}>
              网页挂件嵌入代码（把 HOST 换成你的部署地址）：
            </Typography.Text>
            <Typography.Paragraph
              copyable
              style={{
                marginTop: 6,
                padding: "8px 10px",
                background: "#f6f8fa",
                borderRadius: 6,
                fontSize: 12,
                fontFamily: "monospace",
                whiteSpace: "pre-wrap",
              }}
            >
              {`<script src="https://HOST/widget.js" data-key="${newKey}" defer></script>`}
            </Typography.Paragraph>
          </div>
        )}
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, fontSize: 12 }}>
          API 调用：POST /api/v1/chat/stream，Header 携带 Authorization: Bearer &lt;key&gt;
        </Typography.Paragraph>
      </Modal>
    </Card>
  );
}
