import {
  Badge,
  Button,
  Card,
  Input,
  message,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useState } from "react";
import { api } from "../api/client";

function fmtTime(v: any) {
  return String(v || "").replace("T", " ").slice(0, 19);
}

/** 待审核回答卡片：全文 + 改写编辑 + 通过/还原/驳回（值班主工作面，文本量大） */
function ReviewCard({ row, onDone }: { row: any; onDone: () => void }) {
  const [text, setText] = useState(row.content || "");
  const decide = useMutation({
    mutationFn: (v: { action: string; content?: string }) =>
      api.post(`/api/v1/hitl/reviews/${row.message_id}/decide`, v),
    onSuccess: () => {
      message.success("已处理");
      onDone();
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });
  const changed = text !== (row.content || "");
  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      title={
        <Space wrap>
          <Tag color="blue">{row.app_name}</Tag>
          <Typography.Text>{row.conversation_title || "（未命名会话）"}</Typography.Text>
        </Space>
      }
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {fmtTime(row.created_at)}
        </Typography.Text>
      }
    >
      <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 12 }}>
        {row.content}
      </Typography.Paragraph>
      <Input.TextArea
        rows={Math.min(12, Math.max(3, Math.ceil((text || "").length / 80)))}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="改写后的回答（不改动则通过原文）"
      />
      <Space style={{ marginTop: 8 }}>
        <Button
          type="primary"
          size="small"
          loading={decide.isPending}
          disabled={decide.isPending}
          onClick={() => decide.mutate(changed ? { action: "replace", content: text } : { action: "approve" })}
        >
          {changed ? "改写后通过" : "通过原文"}
        </Button>
        <Button size="small" disabled={!changed || decide.isPending} onClick={() => setText(row.content || "")}>
          还原原文
        </Button>
        <Popconfirm title="驳回后该回答对用户永久不可见，确认？" onConfirm={() => decide.mutate({ action: "reject" })}>
          <Button size="small" danger disabled={decide.isPending}>
            驳回
          </Button>
        </Popconfirm>
      </Space>
    </Card>
  );
}

/** 人机协作值班页：跨应用的待审批工具调用 + 待审核回答 */
export default function HumanLoop() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const appId = params.get("app") || undefined;
  const [tab, setTab] = useState("approvals");

  const { data: apps } = useQuery({
    queryKey: ["apps"],
    queryFn: () => api.get<any[]>("/api/v1/apps"),
  });
  const { data: counts } = useQuery({
    queryKey: ["hitl-counts"],
    queryFn: () => api.get<{ approvals: number; reviews: number }>("/api/v1/hitl/counts"),
    refetchInterval: 15000,
  });
  const { data: approvals } = useQuery({
    queryKey: ["hitl-approvals", appId],
    queryFn: () => api.get<any[]>(`/api/v1/hitl/approvals${appId ? `?app_id=${appId}` : ""}`),
    refetchInterval: 15000,
  });
  const { data: reviews } = useQuery({
    queryKey: ["hitl-reviews", appId],
    queryFn: () => api.get<any[]>(`/api/v1/hitl/reviews${appId ? `?app_id=${appId}` : ""}`),
    refetchInterval: 15000,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["hitl-approvals"] });
    qc.invalidateQueries({ queryKey: ["hitl-reviews"] });
    qc.invalidateQueries({ queryKey: ["hitl-counts"] });
    qc.invalidateQueries({ queryKey: ["apps"] });
  };
  const decide = useMutation({
    mutationFn: (v: { id: string; approved: boolean }) =>
      api.post(`/api/v1/hitl/approvals/${v.id}/decide`, { approved: v.approved }),
    onSuccess: () => {
      message.success("已处理，执行结果已自动回复到原对话");
      refresh();
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  const approvalsTable = (
    <Table
      rowKey="id"
      size="small"
      dataSource={approvals || []}
      locale={{ emptyText: "没有待审批的工具调用。给敏感工具开启「调用前需人工确认」后，调用会落到这里等你放行。" }}
      columns={[
        { title: "应用", dataIndex: "app_name", width: 140, ellipsis: true },
        { title: "工具", dataIndex: "tool_name", width: 140, ellipsis: true },
        {
          title: "参数",
          dataIndex: "args",
          render: (v) => (
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                maxHeight: 160,
                overflow: "auto",
                fontSize: 12,
              }}
            >
              {JSON.stringify(v, null, 2)}
            </pre>
          ),
        },
        {
          title: "时间",
          dataIndex: "created_at",
          width: 150,
          render: (v) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{fmtTime(v)}</Typography.Text>,
        },
        {
          title: "",
          width: 150,
          render: (_, r) => (
            <Space>
              <Button
                size="small"
                type="primary"
                loading={decide.isPending && decide.variables?.id === r.id}
                onClick={() => decide.mutate({ id: r.id, approved: true })}
              >
                通过执行
              </Button>
              <Popconfirm title="拒绝执行该调用？" onConfirm={() => decide.mutate({ id: r.id, approved: false })}>
                <Button size="small" danger>
                  拒绝
                </Button>
              </Popconfirm>
            </Space>
          ),
        },
      ]}
    />
  );

  const reviewsList = (reviews || []).length ? (
    (reviews || []).map((r) => <ReviewCard key={r.message_id} row={r} onDone={refresh} />)
  ) : (
    <Card size="small">
      <Typography.Text type="secondary">
        没有待审核的回答。应用配置里开启「回答人工审核」后，每轮回答会先落到这里等你放行。
      </Typography.Text>
    </Card>
  );

  return (
    <div>
      <Space style={{ marginBottom: 16 }} align="center">
        <Typography.Title level={4} style={{ margin: 0 }}>
          人机协作
        </Typography.Title>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          style={{ width: 220 }}
          placeholder="全部应用"
          value={appId}
          onChange={(v) => setParams(v ? { app: v } : {})}
          options={(apps || []).map((a) => ({ value: a.id, label: a.name }))}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          待办每 15 秒自动刷新
        </Typography.Text>
      </Space>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "approvals",
            label: (
              <Badge count={approvals?.length || 0} size="small" offset={[10, 0]}>
                待审批工具调用
              </Badge>
            ),
            children: approvalsTable,
          },
          {
            key: "reviews",
            label: (
              <Badge count={reviews?.length || 0} size="small" offset={[10, 0]}>
                待审核回答
              </Badge>
            ),
            children: reviewsList,
          },
        ]}
      />
    </div>
  );
}
