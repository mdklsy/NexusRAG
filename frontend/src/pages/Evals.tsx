import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Popover,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { PlayCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

/* 评测页：选应用 → 评测集管理 → 运行 → 结果轮询 */

interface EvalSetRow {
  id: string;
  app_id: string;
  name: string;
  description: string;
  created_at: string;
}

interface RunDetail {
  id: string;
  status: string;
  total: number;
  done: number;
  avg_faithfulness: number | null;
  avg_relevance: number | null;
  avg_context_sufficiency?: number | null;
  hit_rate: number | null;
  error: string | null;
  results: {
    question: string;
    answer: string;
    retrieved_doc_names: string[];
    diagnosis?: { cause: string; detail: string; suggestion: string } | null;
    faithfulness: number | null;
    context_sufficiency?: number | null;
    relevance: number | null;
    hit: boolean | null;
    elapsed_ms: number;
    error: string | null;
  }[];
}

export default function Evals() {
  const qc = useQueryClient();
  const [appId, setAppId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const { data: apps } = useQuery({
    queryKey: ["apps"],
    queryFn: () => api.get<any[]>("/api/v1/apps"),
  });
  const { data: sets } = useQuery({
    queryKey: ["evalSets", appId],
    queryFn: () => api.get<EvalSetRow[]>(`/api/v1/apps/${appId}/eval-sets`),
    enabled: !!appId,
  });
  const { data: run } = useQuery({
    queryKey: ["evalRun", activeRunId],
    queryFn: () => api.get<RunDetail>(`/api/v1/eval-runs/${activeRunId}`),
    enabled: !!activeRunId,
    refetchInterval: (q) =>
      q.state.data && ["pending", "running"].includes(q.state.data.status) ? 1500 : false,
  });

  const create = useMutation({
    mutationFn: (v: any) => {
      // "问题 | 要点 | 文档名" 每行一条 → cases 数组
      const cases = (v.cases_text || "")
        .split("\n")
        .map((line: string) => line.trim())
        .filter(Boolean)
        .map((line: string) => {
          const [question, expected_points = "", expected_doc_name = ""] =
            line.split("|").map((s: string) => s.trim());
          return { question, expected_points, expected_doc_name };
        });
      return api.post(`/api/v1/apps/${appId}/eval-sets`, {
        name: v.name,
        cases,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["evalSets", appId] });
      setCreateOpen(false);
      form.resetFields();
      message.success("评测集已创建");
    },
    onError: (e: any) => message.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/eval-sets/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["evalSets", appId] }),
  });

  const runEval = useMutation({
    mutationFn: (setId: string) => api.post<any>(`/api/v1/eval-sets/${setId}/run`),
    onSuccess: (data) => {
      setActiveRunId(data.id);
      message.info("评测已启动");
    },
    onError: (e: any) => message.error(e.message),
  });

  const STATUS_TAG: Record<string, [string, string]> = {
    pending: ["default", "排队中"],
    running: ["processing", "运行中"],
    completed: ["success", "已完成"],
    failed: ["error", "失败"],
  };

const DIAG_CAUSE: Record<string, { color: string; text: string }> = {
  no_recall: { color: "red", text: "召回为空" },
  recall_miss: { color: "red", text: "期望文档未召回" },
  ranking: { color: "orange", text: "排序靠后" },
  context_gap: { color: "orange", text: "资料不足" },
  generation: { color: "purple", text: "生成问题" },
};

  return (
    <Space direction="vertical" style={{ width: "100%" }} size={16}>
      <Card
        title="问答评测"
        extra={
          <Space>
            <Select
              style={{ width: 220 }}
              placeholder="选择应用"
              value={appId}
              onChange={(v) => {
                setAppId(v);
                setActiveRunId(null);
              }}
              options={(apps || []).map((a) => ({ value: a.id, label: `${a.icon} ${a.name}` }))}
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!appId}
              onClick={() => setCreateOpen(true)}
            >
              新建评测集
            </Button>
          </Space>
        }
      >
        {!appId && <Empty description="先选择要评测的应用" style={{ padding: 40 }} />}
        {appId && (
          <Table<EvalSetRow>
            rowKey="id"
            dataSource={sets || []}
            locale={{ emptyText: "还没有评测集。录入一批问题与期望答案，量化检索与回答质量。" }}
            columns={[
              { title: "评测集", dataIndex: "name" },
              { title: "创建时间", dataIndex: "created_at", render: (v) => v?.slice(0, 16).replace("T", " ") },
              {
                title: "操作",
                width: 220,
                render: (_, r) => (
                  <Space>
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<PlayCircleOutlined />}
                      loading={runEval.isPending && runEval.variables === r.id}
                      onClick={() => runEval.mutate(r.id)}
                    >
                      运行
                    </Button>
                    <Button size="small" danger type="text" onClick={() => remove.mutate(r.id)}>
                      删除
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      {run && (
        <Card
          title={`运行结果 ${run.status === "running" ? `（${run.done}/${run.total}）` : ""}`}
          extra={
            STATUS_TAG[run.status] ? (
              <Tag color={STATUS_TAG[run.status][0]}>{STATUS_TAG[run.status][1]}</Tag>
            ) : null
          }
        >
          {run.error && (
            <Typography.Paragraph type="danger">{run.error}</Typography.Paragraph>
          )}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={5}>
              <Statistic
                title="忠实度 (1-5)"
                value={run.avg_faithfulness?.toFixed(2) ?? "—"}
                suffix={run.avg_faithfulness ? "/ 5" : ""}
              />
            </Col>
            <Col span={5}>
              <Statistic title="相关性 (1-5)" value={run.avg_relevance?.toFixed(2) ?? "—"} />
            </Col>
            <Col span={5}>
              <Statistic
                title="资料充分度 (1-5)"
                value={run.avg_context_sufficiency?.toFixed(2) ?? "—"}
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="文档命中率"
                value={run.hit_rate != null ? (run.hit_rate * 100).toFixed(0) : "—"}
                suffix={run.hit_rate != null ? "%" : ""}
              />
            </Col>
            <Col span={5}>
              <Statistic title="用例数" value={run.total} />
            </Col>
          </Row>
          <Table
            rowKey={(r: any) => r.question}
            size="small"
            dataSource={run.results || []}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: "问题", dataIndex: "question", ellipsis: true, width: 220 },
              { title: "回答", dataIndex: "answer", ellipsis: true },
              {
                title: "忠实",
                dataIndex: "faithfulness",
                width: 70,
                render: (v) => (v != null ? v.toFixed(0) : "—"),
              },
              {
                title: "相关",
                dataIndex: "relevance",
                width: 70,
                render: (v) => (v != null ? v.toFixed(0) : "—"),
              },
              {
                title: "诊断",
                dataIndex: "diagnosis",
                width: 110,
                render: (d) => {
                  if (!d?.cause) return "—";
                  const meta = DIAG_CAUSE[d.cause] || { color: "default", text: d.cause };
                  return (
                    <Popover
                      title="失败归因"
                      content={
                        <div style={{ maxWidth: 320 }}>
                          <div>{d.detail}</div>
                          <Typography.Paragraph
                            type="secondary"
                            style={{ marginBottom: 0, marginTop: 8, fontSize: 12 }}
                          >
                            修复建议：{d.suggestion}
                          </Typography.Paragraph>
                        </div>
                      }
                    >
                      <Tag color={meta.color}>{meta.text}</Tag>
                    </Popover>
                  );
                },
              },
              {
                title: "命中",
                dataIndex: "hit",
                width: 70,
                render: (v) =>
                  v == null ? "—" : v ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>,
              },
              {
                title: "耗时",
                dataIndex: "elapsed_ms",
                width: 80,
                render: (v) => `${v}ms`,
              },
            ]}
          />
        </Card>
      )}

      <Modal
        title="新建评测集"
        open={createOpen}
        width={720}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.validateFields().then((v) => create.mutate(v))}
        confirmLoading={create.isPending}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          每行一个用例：问题 | 期望要点（供打分参考） | 期望命中文档名（可空，判命中率）。
          用「|」分隔，至少一个问题。
        </Typography.Paragraph>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如：客服知识库 v1 验收" />
          </Form.Item>
          <Form.Item
            name="cases_text"
            label="用例（每行：问题 | 期望要点 | 期望文档名）"
            rules={[{ required: true, message: "请录入至少一条用例" }]}
          >
            <Input.TextArea
              rows={8}
              placeholder={
                "退款政策是什么 | 七天无理由、运费自理 | 退款政策.md\n怎么开发票 | 电子发票、纸质发票 | \n你们老板是谁 |  | "
              }
            />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
