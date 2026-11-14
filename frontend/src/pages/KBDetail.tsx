import {
  Button,
  Card,
  Col,
  Drawer,
  Input,
  List,
  message,
  Modal,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  Radio,
  Select,
} from "antd";
import { LinkOutlined, UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api, upload } from "../api/client";
import { useEffect, useState } from "react";

interface Doc {
  id: string;
  name: string;
  source_type: string;
  status: string;
  error: string | null;
  chunk_count: number;
  size_bytes: number;
  created_at: string;
  acl?: { mode: string; end_users?: string[]; claims?: { key: string; values: string[] }[] } | null;
}

const STATUS_TAG: Record<string, [string, string]> = {
  pending: ["default", "排队中"],
  parsing: ["processing", "解析中"],
  chunking: ["processing", "分块中"],
  embedding: ["processing", "向量化"],
  extracting_kg: ["processing", "图谱抽取"],
  completed: ["success", "已完成"],
  failed: ["error", "失败"],
};
const IN_FLIGHT = ["pending", "parsing", "chunking", "embedding", "extracting_kg"];

export default function KBDetail() {
  const { kbId } = useParams();
  const qc = useQueryClient();
  const [urlOpen, setUrlOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [chunkDoc, setChunkDoc] = useState<Doc | null>(null);

  const { data: kb } = useQuery({
    queryKey: ["kb", kbId],
    queryFn: () => api.get<any>(`/api/v1/kbs/${kbId}`),
  });
  const { data: docs } = useQuery({
    queryKey: ["docs", kbId],
    queryFn: () => api.get<Doc[]>(`/api/v1/kbs/${kbId}/documents`),
    refetchInterval: (q) =>
      (q.state.data || []).some((d) => IN_FLIGHT.includes(d.status)) ? 2000 : false,
  });
  const { data: kgStats } = useQuery({
    queryKey: ["kgStats", kbId],
    queryFn: () => api.get<any>(`/api/v1/kbs/${kbId}/kg-stats`),
  });

  const { data: chunks } = useQuery({
    queryKey: ["chunks", chunkDoc?.id],
    queryFn: () => api.get<any[]>(`/api/v1/documents/${chunkDoc!.id}/chunks`),
    enabled: !!chunkDoc,
  });

  const del = useMutation({
    mutationFn: (id: string) => api.del(`/api/v1/documents/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["docs", kbId] });
      qc.invalidateQueries({ queryKey: ["kb", kbId] });
      message.success("已删除");
    },
  });

  // 重新分块：清空已生成的分块/图谱并重跑摄取管线（失败重试、卡死恢复）
  const reingest = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/documents/${id}/reprocess`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["docs", kbId] });
      message.success("已重新加入摄取队列");
    },
    onError: (e: any) => message.error(e.message),
  });

  const addUrl = useMutation({
    mutationFn: () => api.post(`/api/v1/kbs/${kbId}/documents/url`, { url }),
    onSuccess: () => {
      setUrlOpen(false);
      setUrl("");
      qc.invalidateQueries({ queryKey: ["docs", kbId] });
      message.success("已加入抓取队列");
    },
    onError: (e: any) => message.error(e.message),
  });

  const uploading = useMutation({
    mutationFn: (file: File) => upload(`/api/v1/kbs/${kbId}/documents/upload`, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["docs", kbId] });
      message.success("上传成功，摄取中");
    },
    onError: (e: any) => message.error("上传失败: " + e.message),
  });

  useEffect(() => {
    if (docs?.length) qc.invalidateQueries({ queryKey: ["kgStats", kbId] });
  }, [docs?.length]);

  // 文档级 ACL：public=所有人可见；restricted=仅白名单终端用户（挂件按 end_user 过滤检索）
  const [aclDoc, setAclDoc] = useState<Doc | null>(null);
  const [aclMode, setAclMode] = useState<"public" | "restricted">("public");
  const [aclUsers, setAclUsers] = useState("");
  // 属性声明条件（ACL v2）：[{key, values[]}]；对接系统传什么声明就按条件匹配，无需登记用户 ID
  const [aclClaims, setAclClaims] = useState<{ key: string; values: string[] }[]>([]);
  // 块级 ACL（覆盖模式）
  const [aclChunk, setAclChunk] = useState<any | null>(null);
  const [chunkAclMode, setChunkAclMode] = useState<"inherit" | "public" | "restricted">("inherit");
  const [chunkAclUsers, setChunkAclUsers] = useState("");
  const [chunkAclClaims, setChunkAclClaims] = useState<{ key: string; values: string[] }[]>([]);
  const aclSave = useMutation({
    mutationFn: (v: {
      id: string; mode: string; users: string[];
      claims: { key: string; values: string[] }[];
    }) =>
      api.put(`/api/v1/documents/${v.id}/acl`, {
        mode: v.mode, end_users: v.users, claims: v.claims,
      }),
    onSuccess: () => {
      message.success("可见范围已更新");
      setAclDoc(null);
      qc.invalidateQueries({ queryKey: ["docs", kbId] });
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  const chunkAclSave = useMutation({
    mutationFn: (v: {
      id: string; mode: string; users: string[];
      claims: { key: string; values: string[] }[];
    }) =>
      api.put(`/api/v1/chunks/${v.id}/acl`, {
        mode: v.mode, end_users: v.users, claims: v.claims,
      }),
    onSuccess: () => {
      message.success("分块可见范围已更新");
      setAclChunk(null);
      if (chunkDoc) qc.invalidateQueries({ queryKey: ["chunks", chunkDoc.id] });
    },
    onError: (e: any) => message.error(String(e?.message || e)),
  });

  return (
    <Space direction="vertical" style={{ width: "100%" }} size={16}>
      <Card
        title={kb?.name || "知识库"}
        extra={
          <Space>
            <Button icon={<LinkOutlined />} onClick={() => setUrlOpen(true)}>
              导入网页
            </Button>
            <Upload
              showUploadList={false}
              customRequest={({ file }) => uploading.mutate(file as File)}
              accept=".pdf,.docx,.xlsx,.md,.txt,.csv,.html,.htm,.json"
            >
              <Button type="primary" icon={<UploadOutlined />} loading={uploading.isPending}>
                上传文档
              </Button>
            </Upload>
          </Space>
        }
      >
        <Row gutter={16}>
          <Col span={4}>
            <Statistic title="文档" value={kb?.doc_count ?? 0} />
          </Col>
          <Col span={4}>
            <Statistic title="分块" value={kb?.chunk_count ?? 0} />
          </Col>
          <Col span={5}>
            <Statistic title="实体" value={kgStats?.entity_count ?? 0} />
          </Col>
          <Col span={5}>
            <Statistic title="关系" value={kgStats?.relation_count ?? 0} />
          </Col>
          <Col span={6}>
            <Typography.Paragraph style={{ marginBottom: 0 }} type="secondary">
              高频实体：
              {(kgStats?.top_entities || []).slice(0, 5).map((t: any) => t[0]).join("、") || "—"}
            </Typography.Paragraph>
          </Col>
        </Row>
      </Card>

      <Card title="文档列表">
        <Table<Doc>
          rowKey="id"
          dataSource={docs}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "名称", dataIndex: "name", ellipsis: true },
            {
              title: "来源",
              dataIndex: "source_type",
              width: 80,
              render: (v) => (v === "url" ? "网页" : "文件"),
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 110,
              render: (s) => {
                const [color, text] = STATUS_TAG[s] || ["default", s];
                return <Tag color={color}>{text}</Tag>;
              },
            },
            { title: "分块", dataIndex: "chunk_count", width: 80 },
            {
              title: "可见范围",
              dataIndex: "acl",
              width: 100,
              render: (v) =>
                v?.mode === "restricted" ? (
                  <Tag color="purple">指定{(v.end_users || []).length}人</Tag>
                ) : (
                  <Tag color="green">公开</Tag>
                ),
            },
            {
              title: "错误",
              dataIndex: "error",
              ellipsis: true,
              render: (v) =>
                v ? (
                  <Typography.Text type="danger" style={{ fontSize: 12 }}>
                    {v}
                  </Typography.Text>
                ) : (
                  "-"
                ),
            },
            {
              title: "操作",
              width: 280,
              render: (_, r) => (
                <Space size={4}>
                  <Button size="small" onClick={() => setChunkDoc(r)}>
                    预览
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      setAclDoc(r);
                      setAclMode(r.acl?.mode === "restricted" ? "restricted" : "public");
                      setAclUsers((r.acl?.end_users || []).join(", "));
                      setAclClaims(r.acl?.claims || []);
                    }}
                  >
                    可见范围
                  </Button>
                  <Popconfirm
                    title="重新分块该文档？"
                    description="清空已生成的分块与图谱，重新摄取"
                    onConfirm={() => reingest.mutate(r.id)}
                  >
                    <Button size="small" loading={reingest.isPending && reingest.variables === r.id}>
                      重新分块
                    </Button>
                  </Popconfirm>
                  <Popconfirm title="删除该文档？" onConfirm={() => del.mutate(r.id)}>
                    <Button size="small" danger type="text">
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={`可见范围 - ${aclDoc?.name || ""}`}
        open={!!aclDoc}
        onCancel={() => setAclDoc(null)}
        onOk={() =>
          aclSave.mutate({
            id: aclDoc!.id,
            mode: aclMode,
            users: aclUsers.split(/[,，\s]+/).filter(Boolean),
            claims: aclClaims.filter((c) => c.key.trim() && c.values.length),
          })
        }
        confirmLoading={aclSave.isPending}
        okText="保存"
      >
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Radio.Group value={aclMode} onChange={(e) => setAclMode(e.target.value)}>
            <Radio value="public">公开：所有终端用户可见（默认）</Radio>
            <Radio value="restricted">受限：满足下方任一授权规则才可见</Radio>
          </Radio.Group>
          {aclMode === "restricted" && (
            <>
              <Typography.Text style={{ fontSize: 12 }}>属性声明条件（对接系统在 end_user.attributes 里传什么就匹配什么；多条件需同时满足）</Typography.Text>
              {aclClaims.map((c, i) => (
                <Space key={i} style={{ display: "flex", marginBottom: 4 }} wrap>
                  <Input
                    style={{ width: 140 }}
                    placeholder="属性名，如 dept"
                    value={c.key}
                    onChange={(e) => {
                      const next = [...aclClaims];
                      next[i] = { ...next[i], key: e.target.value };
                      setAclClaims(next);
                    }}
                  />
                  <Select
                    mode="tags"
                    style={{ width: 260 }}
                    placeholder="属性值（输入后回车），如 销售部"
                    value={c.values}
                    onChange={(v: string[]) => {
                      const next = [...aclClaims];
                      next[i] = { ...next[i], values: v };
                      setAclClaims(next);
                    }}
                    options={[]}
                    open={false}
                  />
                  <Button
                    size="small"
                    type="text"
                    onClick={() => setAclClaims(aclClaims.filter((_, j) => j !== i))}
                  >
                    删
                  </Button>
                </Space>
              ))}
              <Button size="small" type="dashed" onClick={() => setAclClaims([...aclClaims, { key: "", values: [] }])}>
                添加属性条件
              </Button>
              <Typography.Text style={{ fontSize: 12, display: "block" }}>
                高级：终端用户 ID 白名单（与属性条件任一命中即可见）
              </Typography.Text>
              <Input.TextArea
                rows={2}
                value={aclUsers}
                onChange={(e) => setAclUsers(e.target.value)}
                placeholder="终端用户 ID，逗号分隔（可选，一般用属性声明就够了）"
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                受限生效后：挂件检索会过滤该文档（含 BM25 与向量）；知识图谱事实不参与过滤，敏感文档所在库建议关闭 KG 增强
              </Typography.Text>
            </>
          )}
        </Space>
      </Modal>

      <Modal
        title="导入网页"
        open={urlOpen}
        onCancel={() => setUrlOpen(false)}
        onOk={() => addUrl.mutate()}
        confirmLoading={addUrl.isPending}
      >
        <Input
          placeholder="https://example.com/help"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      </Modal>

      <Drawer
        title={`分块预览 - ${chunkDoc?.name || ""}`}
        open={!!chunkDoc}
        onClose={() => setChunkDoc(null)}
        width={620}
      >
        <List
          dataSource={chunks || []}
          renderItem={(c: any) => (
            <List.Item
              actions={[
                <Button
                  key="acl"
                  size="small"
                  onClick={() => {
                    setAclChunk(c);
                    const m = c.acl?.mode || "inherit";
                    setChunkAclMode(m === "public" || m === "restricted" ? m : "inherit");
                    setChunkAclUsers((c.acl?.end_users || []).join(", "));
                    setChunkAclClaims(c.acl?.claims || []);
                  }}
                >
                  权限
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={6}>
                    <span>{`#${c.seq} · ~${c.token_count} tokens${c.meta?.heading ? ` · ${c.meta.heading}` : ""}`}</span>
                    {!c.acl && <Tag style={{ fontSize: 11 }}>继承文档</Tag>}
                    {c.acl?.mode === "public" && <Tag color="green" style={{ fontSize: 11 }}>块公开</Tag>}
                    {c.acl?.mode === "restricted" && (
                      <Tag color="purple" style={{ fontSize: 11 }}>块受限</Tag>
                    )}
                  </Space>
                }
                description={
                  <Typography.Paragraph ellipsis={{ rows: 4 }} style={{ marginBottom: 0 }}>
                    {c.content}
                  </Typography.Paragraph>
                }
              />
            </List.Item>
          )}
        />
      </Drawer>

      <Modal
        title={`分块权限 - #${aclChunk?.seq ?? ""}`}
        open={!!aclChunk}
        onCancel={() => setAclChunk(null)}
        onOk={() =>
          chunkAclSave.mutate({
            id: aclChunk!.id,
            mode: chunkAclMode,
            users: chunkAclUsers.split(/[,，\s]+/).filter(Boolean),
            claims: chunkAclClaims.filter((c) => c.key.trim() && c.values.length),
          })
        }
        confirmLoading={chunkAclSave.isPending}
        okText="保存"
      >
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Radio.Group value={chunkAclMode} onChange={(e) => setChunkAclMode(e.target.value)}>
            <Radio value="inherit">继承文档规则（默认）</Radio>
            <Radio value="public">块级公开（覆盖文档限制，摘录例外用）</Radio>
            <Radio value="restricted">块级受限（公开文档里封锁这段）</Radio>
          </Radio.Group>
          {chunkAclMode === "restricted" && (
            <>
              <Typography.Text style={{ fontSize: 12 }}>属性声明条件（多条件需同时满足）</Typography.Text>
              {chunkAclClaims.map((c, i) => (
                <Space key={i} style={{ display: "flex", marginBottom: 4 }} wrap>
                  <Input
                    style={{ width: 140 }}
                    placeholder="属性名，如 dept"
                    value={c.key}
                    onChange={(e) => {
                      const next = [...chunkAclClaims];
                      next[i] = { ...next[i], key: e.target.value };
                      setChunkAclClaims(next);
                    }}
                  />
                  <Select
                    mode="tags"
                    style={{ width: 260 }}
                    placeholder="属性值（输入后回车）"
                    value={c.values}
                    onChange={(v: string[]) => {
                      const next = [...chunkAclClaims];
                      next[i] = { ...next[i], values: v };
                      setChunkAclClaims(next);
                    }}
                    options={[]}
                    open={false}
                  />
                  <Button
                    size="small"
                    type="text"
                    onClick={() => setChunkAclClaims(chunkAclClaims.filter((_, j) => j !== i))}
                  >
                    删
                  </Button>
                </Space>
              ))}
              <Button size="small" type="dashed" onClick={() => setChunkAclClaims([...chunkAclClaims, { key: "", values: [] }])}>
                添加属性条件
              </Button>
              <Typography.Text style={{ fontSize: 12, display: "block" }}>
                高级：终端用户 ID 白名单
              </Typography.Text>
              <Input.TextArea
                rows={2}
                value={chunkAclUsers}
                onChange={(e) => setChunkAclUsers(e.target.value)}
                placeholder="终端用户 ID，逗号分隔（可选）"
              />
            </>
          )}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            覆盖模式：块规则设置后该块可见性完全由块规则决定（不再看文档规则）；「继承文档」恢复默认
          </Typography.Text>
        </Space>
      </Modal>
    </Space>
  );
}
