import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useState } from "react";
import { api } from "../api/client";

const GAP_STATUS: Record<string, { color: string; text: string }> = {
  open: { color: "orange", text: "待处理" },
  drafted: { color: "blue", text: "已起草" },
  resolved: { color: "green", text: "已解决" },
};

/** 洞察页：审核数据飞轮（统计/规则挖掘/驳回转评测）+ 知识缺口发现 */
export default function Insights() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const appId = params.get("app");
  const [rules, setRules] = useState<any[]>([]);
  const [selectedRejected, setSelectedRejected] = useState<string[]>([]);
  const [draftView, setDraftView] = useState<any | null>(null);

  const { data: apps } = useQuery({
    queryKey: ["apps"],
    queryFn: () => api.get<any[]>("/api/v1/apps"),
  });
  const { data: stats } = useQuery({
    queryKey: ["insights-stats", appId],
    queryFn: () => api.get<any>(`/api/v1/apps/${appId}/insights/stats`),
    enabled: !!appId,
  });
  const { data: rejected } = useQuery({
    queryKey: ["insights-rejected", appId],
    queryFn: () => api.get<any[]>(`/api/v1/apps/${appId}/insights/rejected`),
    enabled: !!appId,
  });
  const { data: gaps } = useQuery({
    queryKey: ["insights-gaps", appId],
    queryFn: () => api.get<any[]>(`/api/v1/apps/${appId}/insights/gaps`),
    enabled: !!appId,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["insights-stats"] });
    qc.invalidateQueries({ queryKey: ["insights-gaps"] });
    qc.invalidateQueries({ queryKey: ["insights-rejected"] });
  };

  const mine = useMutation({
    mutationFn: () => api.post<any>(`/api/v1/apps/${appId}/insights/mine-rules`, {}),
    onSuccess: (d) => {
      setRules(d.rules || []);
      if (!(d.rules || []).length) message.info("还没有改写记录可挖掘：先在「人机协作」里改写几条回答");
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  const applyRule = useMutation({
    mutationFn: async (rule: string) => {
      const app = await api.get<any>(`/api/v1/apps/${appId}`);
      const prompt = (app.system_prompt || "").trimEnd();
      const addition = `\n\n【回答规则（来自人工审核改写挖掘）】\n- ${rule}`;
      return api.put(`/api/v1/apps/${appId}`, { system_prompt: prompt + addition });
    },
    onSuccess: () => message.success("已追加到应用系统提示词（保存生效）"),
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  const toEval = useMutation({
    mutationFn: () =>
      api.post<any>(`/api/v1/apps/${appId}/insights/rejected/to-eval`, {
        message_ids: selectedRejected,
      }),
    onSuccess: (d) => {
      message.success(`已创建 ${d.created} 条评测用例（评测集：审核驳回回归）`);
      setSelectedRejected([]);
      refresh();
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  const analyze = useMutation({
    mutationFn: () => api.post<any>(`/api/v1/apps/${appId}/insights/gaps/analyze`, { days: 30 }),
    onSuccess: (d) => {
      refresh();
      message.info(d.length ? `发现 ${d.length} 个知识缺口主题` : "近期没有无答案问题，暂无缺口");
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  const draft = useMutation({
    mutationFn: (id: string) => api.post<any>(`/api/v1/apps/${appId}/insights/gaps/${id}/draft`, {}),
    onSuccess: (g) => {
      refresh();
      setDraftView(g);
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  const resolve = useMutation({
    mutationFn: (id: string) => api.post<any>(`/api/v1/apps/${appId}/insights/gaps/${id}/resolve`, {}),
    onSuccess: () => {
      refresh();
      message.success("已标记解决");
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  return (
    <div>
      <Space style={{ marginBottom: 16 }} align="center">
        <Typography.Title level={4} style={{ margin: 0 }}>
          洞察
        </Typography.Title>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          style={{ width: 220 }}
          placeholder="选择应用"
          value={appId}
          onChange={(v) => setParams(v ? { app: v } : {})}
          options={(apps || []).map((a) => ({ value: a.id, label: a.name }))}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          审核改写与无答案问题是系统进化的原料：规则进提示词、驳回进评测、缺口进知识库
        </Typography.Text>
      </Space>

      {!appId ? (
        <Card>
          <Empty description="选择一个应用查看洞察" />
        </Card>
      ) : (
        <>
          <Row gutter={12} style={{ marginBottom: 16 }}>
            <Col span={3}>
              <Card size="small"><Statistic title="审核总数(30天)" value={stats?.decided ?? 0} /></Card>
            </Col>
            <Col span={3}>
              <Card size="small"><Statistic title="通过" value={stats?.approved ?? 0} /></Card>
            </Col>
            <Col span={3}>
              <Card size="small"><Statistic title="改写" value={stats?.replaced ?? 0} /></Card>
            </Col>
            <Col span={3}>
              <Card size="small"><Statistic title="驳回" value={stats?.rejected ?? 0} /></Card>
            </Col>
            <Col span={3}>
              <Card size="small"><Statistic title="改写率" value={((stats?.replace_rate ?? 0) * 100).toFixed(1)} suffix="%" /></Card>
            </Col>
            <Col span={3}>
              <Card size="small"><Statistic title="提问数(30天)" value={stats?.total_questions ?? 0} /></Card>
            </Col>
            <Col span={3}>
              <Card size="small">
                <Statistic title="无答案率" value={((stats?.no_hit_rate ?? 0) * 100).toFixed(1)} suffix="%" />
              </Card>
            </Col>
          </Row>

          <Card size="small" title="规则挖掘（审核改写 → 提示词规则）" style={{ marginBottom: 16 }}
            extra={<Button size="small" type="primary" loading={mine.isPending} onClick={() => mine.mutate()}>挖掘规则</Button>}>
            {rules.length ? (
              <Table
                rowKey="rule"
                size="small"
                pagination={false}
                dataSource={rules}
                columns={[
                  { title: "规则", dataIndex: "rule" },
                  { title: "例数", dataIndex: "examples", width: 70 },
                  {
                    title: "",
                    width: 130,
                    render: (_, r) => (
                      <Popconfirm title="追加到该应用的系统提示词？" onConfirm={() => applyRule.mutate(r.rule)}>
                        <Button size="small" loading={applyRule.isPending}>应用到提示词</Button>
                      </Popconfirm>
                    ),
                  },
                ]}
              />
            ) : (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                点「挖掘规则」分析最近的改写记录（原文→改写稿对照），提炼成可一键写入提示词的写作规则
              </Typography.Text>
            )}
          </Card>

          <Card size="small" title="审核驳回 → 评测回归" style={{ marginBottom: 16 }}
            extra={
              <Button size="small" type="primary" disabled={!selectedRejected.length}
                loading={toEval.isPending} onClick={() => toEval.mutate()}>
                转入评测集({selectedRejected.length})
              </Button>
            }>
            <Table
              rowKey="message_id"
              size="small"
              pagination={false}
              dataSource={rejected || []}
              locale={{ emptyText: "没有被驳回的回答。审核时驳回的问题会出现在这里，一键转为评测用例形成回归防线" }}
              rowSelection={{ selectedRowKeys: selectedRejected, onChange: (k: any) => setSelectedRejected(k) }}
              columns={[
                { title: "用户提问", dataIndex: "question", ellipsis: true },
                { title: "被驳回的回答", dataIndex: "rejected_answer", ellipsis: true },
                { title: "时间", dataIndex: "created_at", width: 150, render: (v) => String(v || "").replace("T", " ").slice(0, 19) },
              ]}
            />
          </Card>

          <Card size="small" title="知识缺口（无答案问题聚类）"
            extra={<Button size="small" type="primary" loading={analyze.isPending} onClick={() => analyze.mutate()}>分析缺口</Button>}>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={gaps || []}
              locale={{ emptyText: "还没有分析过。点「分析缺口」聚类近 30 天检索未命中的用户问题" }}
              columns={[
                { title: "主题", dataIndex: "theme" },
                {
                  title: "代表问题",
                  dataIndex: "representative_questions",
                  ellipsis: true,
                  render: (v: string[]) => (v || []).slice(0, 3).join("；"),
                },
                { title: "次数", dataIndex: "occurrences", width: 70 },
                {
                  title: "状态",
                  dataIndex: "status",
                  width: 90,
                  render: (v) => <Tag color={GAP_STATUS[v]?.color}>{GAP_STATUS[v]?.text || v}</Tag>,
                },
                {
                  title: "",
                  width: 200,
                  render: (_, r) => (
                    <Space>
                      {r.status !== "resolved" && (
                        <Button size="small" loading={draft.isPending && draft.variables === r.id}
                          onClick={() => draft.mutate(r.id)}>
                          {r.status === "drafted" ? "重新起草" : "生成草稿"}
                        </Button>
                      )}
                      {r.status !== "resolved" && (
                        <Popconfirm title="标记为已解决（通常是你已补充了相关文档）？"
                          onConfirm={() => resolve.mutate(r.id)}>
                          <Button size="small">已解决</Button>
                        </Popconfirm>
                      )}
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </>
      )}

      <Modal
        title={`候选草稿 - ${draftView?.theme || ""}`}
        open={!!draftView}
        width={640}
        onCancel={() => setDraftView(null)}
        footer={null}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          草稿基于通用知识生成，仅供运营参考；确认方向后请补充/修正真实资料到知识库，而不是直接采信数字
        </Typography.Paragraph>
        <Input.TextArea rows={12} value={draftView?.draft_answer || ""} readOnly />
      </Modal>
    </div>
  );
}
