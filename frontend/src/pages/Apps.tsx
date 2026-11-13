import {
  Alert,
  Badge,
  Button,
  ColorPicker,
  Card,
  Radio,
  Tabs,
  Upload,
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
import {
  ApiOutlined,
  CommentOutlined,
  CustomerServiceOutlined,
  KeyOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useNavigate } from "react-router-dom";
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
  pending_approvals?: number;
  pending_reviews?: number;
}

const ICONS = ["🤖", "💬", "📚", "🛎️", "🎯", "💡", "⚖️", "🏥", "🏢", "🛒"];

function BubblePreview({ value }: { value?: string }) {
  const v = value || "icon:comment";
  let inner: any;
  if (v.startsWith("img:")) {
    inner = (
      <img
        src={v.slice(4)}
        alt="bubble"
        style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "50%" }}
      />
    );
  } else {
    const key = v.startsWith("icon:") ? v.slice(5) : "";
    const map: Record<string, any> = {
      comment: <CommentOutlined />,
      headset: <CustomerServiceOutlined />,
      robot: <RobotOutlined />,
      send: <SendOutlined />,
    };
    inner = map[key] ?? v; // 旧数据的 emoji 直接展示（兼容）
  }
  return (
    <span
      style={{
        width: 44,
        height: 44,
        borderRadius: "50%",
        background: "#1677ff",
        color: "#fff",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 20,
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      {inner}
    </span>
  );
}

function ConfigForm({
  form,
  kbs,
  editingId,
}: {
  form: any;
  kbs: { id: string; name: string }[];
  editingId?: string;
}) {
  const kgOn = Form.useWatch(["retrieval_config", "use_kg"], form);
  const rerank = Form.useWatch(["retrieval_config", "rerank"], form);
  const bubbleVal = Form.useWatch(["widget_config", "bubble"], form) as string | undefined;
  const rerankCfg = Form.useWatch(["retrieval_config", "rerank_config"], form) as any;
  const agentMode = Form.useWatch(["agent_ui", "mode"], form);
  const agentParallel = Form.useWatch(["agent_ui", "parallel"], form);
  // 工具白名单多选数据源：与业务工具页签共用一份查询缓存
  const { data: agentToolList } = useQuery({
    queryKey: ["tools", editingId],
    queryFn: () => api.get<any[]>(`/api/v1/apps/${editingId}/tools`),
    enabled: !!editingId,
  });
  const agentToolOptions = (agentToolList || []).map((t: any) => ({
    value: t.name,
    label: `${t.name}（${t.type === "http_api" ? "HTTP" : "SQL"}）`,
  }));
  return (
    <Form form={form} layout="vertical" initialValues={{ temperature: 0.3, max_tokens: 2048, top_k: 5, score_threshold: 0.35, use_kg: true, kg_hops: 1, kg_top_entities: 3, history_window: 12, tool_rounds: 2, intent_route: true, use_bm25: true, rerank: "none", model: "", agent_ui: { mode: "single", max_subtasks: 3, workers: [], parallel: true, max_concurrency: 4 } }}>
      <Tabs
        items={[
          { key: "basic", label: "基本信息", forceRender: true, children: (
        <>
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
        </>
      ) },
          { key: "model", label: "模型", forceRender: true, children: (
        <>
      <Typography.Title level={5}>模型（留空 = 使用「设置」页的全局配置）</Typography.Title>
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
        </>
      ) },
          { key: "retrieval", label: "检索策略", forceRender: true, children: (
        <>
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
            name={["retrieval_config", "tool_rounds"]}
            label="工具轮数"
            tooltip="单条消息里 LLM 最多连续调用几轮业务工具。调大可完成「查表结构→查数据→纠错重查」这类长链路，代价是更多 token。"
            extra={<span style={{ fontSize: 12 }}>1~6，默认 2</span>}
          >
            <InputNumber min={1} max={6} style={{ width: "100%" }} />
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
          ]}
        />
      </Form.Item>
      {rerank === "api" && (
        <>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="默认使用「设置」页的全局重排配置；下方留空即用全局，填写后按本应用覆盖"
          />
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name={["retrieval_config", "rerank_config", "api_base"]}
                label="API Base"
                extra={<span style={{ fontSize: 12 }}>留空 = 全局配置</span>}
              >
                <Input placeholder="如 https://api.siliconflow.cn/v1" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name={["retrieval_config", "rerank_config", "model"]}
                label="模型名"
                extra={<span style={{ fontSize: 12 }}>留空 = 全局配置</span>}
              >
                <Input placeholder="BAAI/bge-reranker-v2-m3" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name={["retrieval_config", "rerank_config", "api_key"]}
                label="API Key"
                extra={
                  <span style={{ fontSize: 12 }}>
                    {rerankCfg?.api_key_masked
                      ? `已设置 ${rerankCfg.api_key_masked}，留空保持`
                      : "留空 = 全局配置"}
                  </span>
                }
              >
                <Input.Password placeholder="粘贴密钥（AES 加密存储）" />
              </Form.Item>
            </Col>
          </Row>
        </>
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
        </>
      ) },
          { key: "agents", label: "多代理协作", forceRender: true, children: (
        <>
      <Typography.Title level={5} style={{ marginBottom: 4 }}>
        多代理协作（可选）
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0, marginBottom: 12 }}>
        单代理（默认）：一个模型在工具循环里自主决策。多代理：规划器把问题拆成子任务分发给下列代理各自执行（各自系统提示词与工具白名单），最后汇总回答——能力更强，但耗时与 token 约为单代理的 2~3 倍，简单问答建议保持单代理。
      </Typography.Paragraph>
      <Row gutter={16}>
        <Col span={10}>
          <Form.Item name={["agent_ui", "mode"]} label="协作模式">
            <Radio.Group>
              <Radio.Button value="single">单代理（默认）</Radio.Button>
              <Radio.Button value="planner_workers">多代理</Radio.Button>
            </Radio.Group>
          </Form.Item>
        </Col>
        {agentMode === "planner_workers" && (
          <Col span={5}>
            <Form.Item
              name={["agent_ui", "max_subtasks"]}
              label="最多子任务数"
              extra={<span style={{ fontSize: 12 }}>规划器一次最多拆几个子任务（1~8）</span>}
            >
              <InputNumber min={1} max={8} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        )}
        {agentMode === "planner_workers" && (
          <Col span={5}>
            <Form.Item
              name={["agent_ui", "parallel"]}
              label="并行执行"
              valuePropName="checked"
              tooltip="开启后互不依赖的子任务按依赖波次并发执行（波内受并发数限制），总耗时约等于最慢一波；关闭则严格串行（适合 LLM 供应商并发配额受限的场景）。"
              extra={<span style={{ fontSize: 12 }}>默认开</span>}
            >
              <Switch />
            </Form.Item>
          </Col>
        )}
        {agentMode === "planner_workers" && agentParallel !== false && (
          <Col span={5}>
            <Form.Item
              name={["agent_ui", "max_concurrency"]}
              label="单波最大并发"
              extra={<span style={{ fontSize: 12 }}>同一波同时执行的代理数上限（1~8）</span>}
            >
              <InputNumber min={1} max={8} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        )}
      </Row>
      {agentMode === "planner_workers" && (
        <>
          <Typography.Text strong>代理名单</Typography.Text>
          <Form.List name={["agent_ui", "workers"]}>
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...restField }) => (
                  <Card
                    key={key}
                    size="small"
                    style={{ marginBottom: 8 }}
                    extra={
                      <Popconfirm title="删除该代理？" onConfirm={() => remove(name)}>
                        <Button size="small" danger type="text">
                          删
                        </Button>
                      </Popconfirm>
                    }
                  >
                    <Row gutter={12}>
                      <Col span={6}>
                        <Form.Item
                          {...restField}
                          name={[name, "name"]}
                          label="代理名称"
                          rules={[{ required: true, message: "必填" }]}
                        >
                          <Input placeholder="数据查询员" />
                        </Form.Item>
                      </Col>
                      <Col span={10}>
                        <Form.Item
                          {...restField}
                          name={[name, "system_prompt"]}
                          label="系统提示词（职责）"
                          rules={[{ required: true, message: "必填" }]}
                        >
                          <Input.TextArea rows={2} placeholder="你是任务数据查询专家：调用业务接口查询统计并解读数字。" />
                        </Form.Item>
                      </Col>
                      <Col span={5}>
                        <Form.Item
                          {...restField}
                          name={[name, "tool_names"]}
                          label="工具白名单"
                          tooltip="简单说：不勾 = 所有工具都能用；勾了 = 只能用勾的这几个。比如查数据的代理，就别给它订单接口的权限。勾了名字但「业务工具」页签里其实没有的，会被自动忽略。"
                        >
                          <Select mode="multiple" allowClear placeholder="全部工具" options={agentToolOptions} maxTagCount={2} />
                        </Form.Item>
                      </Col>
                      <Col span={3}>
                        <Form.Item
                          {...restField}
                          name={[name, "max_rounds"]}
                          label="轮数"
                          initialValue={2}
                          tooltip="这个代理回答前最多能连续查几次工具。1 = 查一次就得答；2 = 查完一次还能再查一次（比如先查统计、再查详情）。每多一轮就多一次模型调用，更慢更贵，默认 2 够用。"
                        >
                          <InputNumber min={1} max={6} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                    </Row>
                  </Card>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ max_rounds: 2 })} block>
                  添加代理
                </Button>
              </>
            )}
          </Form.List>
        </>
      )}
        </>
      ) },
          {
            key: "hitl", label: "人机协作", forceRender: true, children: (
        <>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0, fontSize: 12 }}>
        这里只放应用级开关。待审批、待审核是运行中的业务事项，在应用列表的「人机协作」里处理。
      </Typography.Paragraph>
      <Form.Item
        name={["retrieval_config", "review_mode"]}
        label="回答人工审核"
        valuePropName="checked"
        getValueProps={(v) => ({ checked: v === "on" })}
        normalize={(checked) => (checked ? "on" : "off")}
        tooltip="开启后：每轮回答不再直接发给用户，而是进入应用列表「人机协作」的待审核队列，你通过（可改写）后用户才可见。适合对答出内容负责的场景（客服对外话术等）。"
        extra={<span style={{ fontSize: 12 }}>默认关；挂件用户在审核期间看到“回答已生成，等待人工审核”</span>}
      >
        <Switch />
      </Form.Item>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        工具调用审批：到「业务工具」页签，给具体工具勾选「调用前需人工确认」（按工具配置，不在应用级开关）。
      </Typography.Text>
        </>
      ) },
          { key: "widget", label: "网页挂件", forceRender: true, children: (
        <>
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
            extra={<span style={{ fontSize: 12 }}>选色器取色，或直接输入 #hex</span>}
            getValueFromEvent={(c: any) => (typeof c === "string" ? c : c?.toHexString?.() ?? c)}
          >
            <ColorPicker showText disabledAlpha format="hex" defaultValue="#1677ff" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item
            name={["widget_config", "welcome"]}
            label="欢迎语"
            extra={<span style={{ fontSize: 12 }}>用户打开挂件时先展示的一句话</span>}
          >
            <Input placeholder="你好，请问有什么可以帮你？" />
          </Form.Item>
        </Col>
        <Col span={24}>
          <Form.Item
            label="悬浮球图标"
            tooltip="挂件右下角悬浮球的图标：内置图标库任选，或上传一张小图（≤200KB，自动裁圆展示）"
            extra={<span style={{ fontSize: 12 }}>上传图片会覆盖已选图标；保存后即时生效</span>}
          >
            <Space align="center" size={12} wrap>
              <BubblePreview value={bubbleVal} />
              <Form.Item name={["widget_config", "bubble"]} noStyle>
                <Radio.Group defaultValue="icon:comment">
                  <Radio.Button value="icon:comment" title="对话气泡">
                    <CommentOutlined />
                  </Radio.Button>
                  <Radio.Button value="icon:headset" title="客服耳机">
                    <CustomerServiceOutlined />
                  </Radio.Button>
                  <Radio.Button value="icon:robot" title="机器人">
                    <RobotOutlined />
                  </Radio.Button>
                  <Radio.Button value="icon:send" title="发送箭头">
                    <SendOutlined />
                  </Radio.Button>
                </Radio.Group>
              </Form.Item>
              <Upload
                accept="image/*"
                showUploadList={false}
                beforeUpload={(file) => {
                  if (file.size > 200 * 1024) {
                    message.error("图片请小于 200KB");
                    return Upload.LIST_IGNORE;
                  }
                  const reader = new FileReader();
                  reader.onload = () =>
                    form.setFieldValue(["widget_config", "bubble"], "img:" + String(reader.result));
                  reader.readAsDataURL(file);
                  return false;
                }}
              >
                <Button icon={<UploadOutlined />}>上传图片</Button>
              </Upload>
            </Space>
          </Form.Item>
        </Col>
      </Row>
        </>
      ) },
          ...(editingId
            ? [{ key: "tools", label: "业务工具", forceRender: true, children: <ToolsSection appId={editingId} /> }]
            : []),
        ]}
      />
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

  // sql_db 表结构手动刷新（保存时服务端也会自动拉一次）
  const introspect = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/apps/${appId}/tools/${id}/introspect`, {}),
    onSuccess: (t: any) => {
      qc.invalidateQueries({ queryKey: ["tools", appId] });
      const n = t?.config?.schema?.tables?.length ?? 0;
      message.success(`表结构已更新（${n} 张表）`);
    },
    onError: (e: any) => message.error(e.message),
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
            title: "表结构",
            width: 90,
            render: (_, r) =>
              r.type === "sql_db" ? (
                r.config?.schema?.tables?.length ? (
                  <Tag color="blue">{r.config.schema.tables.length} 表</Tag>
                ) : (
                  <Tag>未拉取</Tag>
                )
              ) : null,
          },
          {
            title: "状态",
            dataIndex: "enabled",
            width: 70,
            render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
          },
          {
            title: "",
            width: 170,
            render: (_, r) => (
              <Space>
                <Button size="small" onClick={() => openForm(r)}>
                  编辑
                </Button>
                {r.type === "sql_db" && (
                  <Button
                    size="small"
                    loading={introspect.isPending && introspect.variables === r.id}
                    onClick={() => introspect.mutate(r.id)}
                    title="重新拉取数据库表结构"
                  >
                    拉表结构
                  </Button>
                )}
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
                  extra={<span style={{ fontSize: 12 }}>保存时自动拉取表结构供 LLM 生成 SQL；表结构变化后点列表里的「拉表结构」刷新。</span>}
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
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name={["config", "require_approval"]}
                label="调用前需人工确认"
                valuePropName="checked"
                tooltip="人机协作：代理要调这个工具时不直接执行，先在应用列表的「人机协作」里生成待审批单；你通过后系统才真正执行，并把结果自动回复到原对话。适合退款、发货、发短信这类有真实后果的接口。"
                extra={<span style={{ fontSize: 12 }}>默认关；开启后挂件用户会看到“已提交人工审批”</span>}
              >
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </>
  );
}

export default function Apps() {
  const qc = useQueryClient();
  const nav = useNavigate();
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
    mutationFn: (values: any) => {
      const { agent_ui, ...rest } = values;
      let agentConfig: any = {};
      if (agent_ui?.mode === "planner_workers") {
        agentConfig = {
          mode: "planner_workers",
          max_subtasks: agent_ui.max_subtasks ?? 3,
          parallel: agent_ui.parallel !== false,
          max_concurrency: agent_ui.max_concurrency ?? 4,
          workers: (agent_ui.workers || []).map((w: any) => ({
            name: w.name,
            system_prompt: w.system_prompt,
            ...(w.tool_names?.length ? { tool_names: w.tool_names } : {}),
            max_rounds: w.max_rounds ?? 2,
          })),
        };
      }
      const payload = {
        ...rest,
        retrieval_config: { ...(values.retrieval_config || {}), agent_config: agentConfig },
      };
      return editing
        ? api.put(`/api/v1/apps/${editing.id}`, payload)
        : api.post("/api/v1/apps", payload);
    },
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
    const rawRc = detail.retrieval_config || {};
    const { agent_config: agentCfg, ...rcRest } = rawRc;
    const rc = { top_k: 5, use_kg: true, kg_hops: 1, kg_top_entities: 3, history_window: 12, tool_rounds: 2, intent_route: true, use_bm25: true, rerank: "none", review_mode: "off", ...rcRest };
    form.setFieldsValue({
      ...detail,
      retrieval_config: rc,
      agent_ui:
        agentCfg && agentCfg.mode === "planner_workers"
          ? {
              mode: "planner_workers",
              max_subtasks: agentCfg.max_subtasks ?? 3,
              parallel: agentCfg.parallel !== false,
              max_concurrency: agentCfg.max_concurrency ?? 4,
              workers: (agentCfg.workers || []).map((w: any) => ({
                name: w.name,
                system_prompt: w.system_prompt,
                tool_names: w.tool_names || [],
                max_rounds: w.max_rounds ?? 2,
              })),
            }
          : { mode: "single", max_subtasks: 3, workers: [] },
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
            render: (_, r) => {
              const hitlCount = (r.pending_approvals || 0) + (r.pending_reviews || 0);
              return (
              <Space>
                <Button size="small" onClick={() => openEdit(r)}>
                  配置
                </Button>
                <Badge count={hitlCount} size="small" offset={[-4, 0]}>
                  <Button size="small" onClick={() => nav(`/hitl?app=${r.id}`)}>人机协作</Button>
                </Badge>
                <Button size="small" icon={<KeyOutlined />} onClick={() => { setKeyApp(r); setNewKey(null); }}>
                  API Key
                </Button>
                <Popconfirm title="删除应用？" onConfirm={() => remove.mutate(r.id)}>
                  <Button size="small" danger type="text">
                    删除
                  </Button>
                </Popconfirm>
              </Space>
              );
            },
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
        <ConfigForm form={form} kbs={kbs || []} editingId={editing?.id} />
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
