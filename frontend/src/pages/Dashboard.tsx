import { Card, Col, Row, Statistic, Typography } from "antd";
import ReactECharts from "echarts-for-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export default function Dashboard() {
  const { data: ov } = useQuery({
    queryKey: ["overview"],
    queryFn: () => api.get<any>("/api/v1/dashboard/overview?days=30"),
  });
  const { data: ts } = useQuery({
    queryKey: ["timeseries"],
    queryFn: () => api.get<any[]>("/api/v1/dashboard/timeseries?days=30"),
  });

  const chartOption = {
    tooltip: { trigger: "axis" },
    legend: { data: ["对话次数", "Token 消耗"] },
    grid: { left: 40, right: 40, top: 40, bottom: 30 },
    xAxis: { type: "category", data: (ts || []).map((p) => p.date) },
    yAxis: [
      { type: "value", name: "次数" },
      { type: "value", name: "Token" },
    ],
    series: [
      {
        name: "对话次数",
        type: "bar",
        data: (ts || []).map((p) => p.chats),
        itemStyle: { color: "#1677ff" },
      },
      {
        name: "Token 消耗",
        type: "line",
        yAxisIndex: 1,
        smooth: true,
        data: (ts || []).map((p) => p.tokens),
        itemStyle: { color: "#52c41a" },
      },
    ],
  };

  return (
    <Row gutter={[16, 16]}>
      <Col span={24}>
        <Card>
          <Row gutter={16}>
            <Col span={4}>
              <Statistic title="对话次数（30天）" value={ov?.total_chats ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic title="检索命中率" value={((ov?.hit_rate ?? 0) * 100).toFixed(1)} suffix="%" />
            </Col>
            <Col span={4}>
              <Statistic title="平均延迟" value={ov?.avg_latency_ms ?? 0} suffix="ms" />
            </Col>
            <Col span={4}>
              <Statistic title="Token 输入" value={ov?.total_tokens_in ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic title="Token 输出" value={ov?.total_tokens_out ?? 0} />
            </Col>
          </Row>
        </Card>
      </Col>
      <Col span={24}>
        <Card title="知识资产">
          <Row gutter={16}>
            <Col span={4}><Statistic title="知识库" value={ov?.total_kbs ?? 0} /></Col>
            <Col span={4}><Statistic title="文档" value={ov?.total_documents ?? 0} /></Col>
            <Col span={4}><Statistic title="分块" value={ov?.total_chunks ?? 0} /></Col>
            <Col span={4}><Statistic title="图谱实体" value={ov?.total_entities ?? 0} /></Col>
            <Col span={4}><Statistic title="图谱关系" value={ov?.total_relations ?? 0} /></Col>
            <Col span={4}><Statistic title="应用" value={ov?.total_apps ?? 0} /></Col>
          </Row>
        </Card>
      </Col>
      <Col span={24}>
        <Card title="用量趋势（近 30 天）">
          {(ts || []).length === 0 ? (
            <Typography.Text type="secondary">暂无对话数据，去 Playground 提问试试</Typography.Text>
          ) : (
            <ReactECharts option={chartOption} style={{ height: 320 }} />
          )}
        </Card>
      </Col>
    </Row>
  );
}
