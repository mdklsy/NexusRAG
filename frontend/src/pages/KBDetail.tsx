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
              width: 210,
              render: (_, r) => (
                <Space size={4}>
                  <Button size="small" onClick={() => setChunkDoc(r)}>
                    预览
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
            <List.Item>
              <List.Item.Meta
                title={`#${c.seq} · ~${c.token_count} tokens${c.meta?.heading ? ` · ${c.meta.heading}` : ""}`}
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
    </Space>
  );
}
