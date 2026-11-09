import {
  Button,
  Card,
  Col,
  Drawer,
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
  return (
    <Form form={form} layout="vertical" initialValues={{ icon: "🤖", temperature: 0.3, max_tokens: 2048, top_k: 5, score_threshold: 0.35, use_kg: true, kg_hops: 1, kg_top_entities: 3, history_window: 6, intent_route: true, model: "" }}>
      <Row gutter={12}>
        <Col span={2}>
          <Form.Item name="icon" label="图标">
            <Select options={ICONS.map((i) => ({ value: i, label: i }))} />
          </Form.Item>
        </Col>
        <Col span={10}>
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
      <Typography.Title level={5}>模型</Typography.Title>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={["llm_config", "model"]} label="模型（留空用全局默认）">
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
      </Row>
      <Typography.Title level={5}>检索策略</Typography.Title>
      <Row gutter={12}>
        <Col span={6}>
          <Form.Item name={["retrieval_config", "top_k"]} label="Top K">
            <InputNumber min={1} max={20} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item name={["retrieval_config", "score_threshold"]} label="相似度阈值">
            <InputNumber min={0} max={1} step={0.05} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item name={["retrieval_config", "history_window"]} label="历史轮数">
            <InputNumber min={0} max={20} style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item name={["retrieval_config", "intent_route"]} label="意图路由" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Col>
        <Col span={24}>
          <Space size={16} style={{ marginBottom: 8 }}>
            <Form.Item name={["retrieval_config", "use_kg"]} label="知识图谱增强" valuePropName="checked" noStyle>
              <Switch size="small" />
            </Form.Item>
            <Form.Item name={["retrieval_config", "kg_hops"]} label="子图跳数" noStyle>
              <InputNumber min={1} max={3} size="small" />
            </Form.Item>
            <Form.Item name={["retrieval_config", "kg_top_entities"]} label="实体数" noStyle>
              <InputNumber min={1} max={10} size="small" />
            </Form.Item>
            <Typography.Text type="secondary">（图谱增强：实体链接 → 子图召回 → 事实注入）</Typography.Text>
          </Space>
        </Col>
      </Row>
    </Form>
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
    mutationFn: () => api.post<any>(`/api/v1/apps/${keyApp!.id}/api-keys?name=console`),
    onSuccess: (data) => {
      setNewKey(data.key);
      qc.invalidateQueries({ queryKey: ["apiKeys", keyApp?.id] });
    },
    onError: (e: any) => message.error(e.message),
  });

  const openEdit = async (app: AppRow) => {
    const detail = await api.get<AppRow>(`/api/v1/apps/${app.id}`);
    setEditing(detail);
    form.setFieldsValue({
      ...detail,
      ...detail.llm_config ? { } : {},
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

      <Drawer
        title={editing ? `配置 - ${editing.name}` : "创建应用"}
        open={creating || !!editing}
        width={680}
        onClose={() => {
          setEditing(null);
          setCreating(false);
        }}
        extra={
          <Button
            type="primary"
            onClick={async () => {
              const values = await form.validateFields();
              save.mutate(values);
            }}
            loading={save.isPending}
          >
            保存
          </Button>
        }
      >
        <ConfigForm form={form} kbs={kbs || []} />
      </Drawer>

      <Modal
        title={`API Keys - ${keyApp?.name || ""}`}
        open={!!keyApp}
        onCancel={() => setKeyApp(null)}
        footer={null}
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
        <Button
          block
          type="dashed"
          icon={<ApiOutlined />}
          style={{ marginTop: 12 }}
          onClick={() => createKey.mutate()}
          loading={createKey.isPending}
        >
          生成新 Key
        </Button>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
          使用方式：POST /api/v1/chat/stream，Header 携带 Authorization: Bearer &lt;key&gt;
        </Typography.Paragraph>
      </Modal>
    </Card>
  );
}
