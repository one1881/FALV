import { useState, useRef, useMemo } from "react";
import { useNavigate } from "react-router";
import {
  ArrowLeft,
  FileText,
  Sparkles,
  Send,
  Image,
  Mic,
  X,
  Loader2,
  Scale,
  Gavel,
  PenLine,
  Briefcase,
  ShoppingCart,
  Users,
  Handshake,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { PageHeader } from "../components/PageHeader";
import { generateContract, type ContractGenerateRequest } from "../../lib/api/contracts";
import { TaskProgress } from "../../app/components/TaskProgress";

type DraftType = {
  key: string;
  label: string;
  description: string;
  icon: React.ElementType;
  placeholder: string;
  color: string;
};

const DRAFT_TYPES: DraftType[] = [
  {
    key: "销售合同",
    label: "销售合同",
    description: "适用于货物销售、产品买卖、购销协议等场景。",
    icon: ShoppingCart,
    placeholder: "请描述销售合同的关键信息：买方/卖方名称、标的物、数量、单价、交付方式、付款条件、违约责任等。",
    color: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  {
    key: "采购合同",
    label: "采购合同",
    description: "适用于企业采购、供应商协议、订货合同等场景。",
    icon: Briefcase,
    placeholder: "请描述采购合同的关键信息：采购方/供应商、采购物品、数量、价格、交货时间、验收标准、付款方式等。",
    color: "bg-sky-50 text-sky-700 border-sky-200",
  },
  {
    key: "服务合同",
    label: "服务合同",
    description: "适用于技术服务、咨询服务、外包服务、维保服务等场景。",
    icon: Handshake,
    placeholder: "请描述服务合同的关键信息：服务内容、服务期限、服务费用、交付标准、保密义务、争议解决等。",
    color: "bg-violet-50 text-violet-700 border-violet-200",
  },
  {
    key: "劳动合同",
    label: "劳动合同",
    description: "适用于员工聘用、劳务派遣、劳动合同补充协议等场景。",
    icon: Users,
    placeholder: "请描述劳动合同的关键信息：用人单位/员工、岗位、薪资、试用期、工作地点、工作时间、社会保险等。",
    color: "bg-amber-50 text-amber-700 border-amber-200",
  },
  {
    key: "起诉状",
    label: "起诉状",
    description: "民事/商事诉讼一审起诉状，支持上传证据图片与录音。",
    icon: Scale,
    placeholder: "请描述案件信息：原告/被告、诉讼请求、事实与理由、证据线索等。",
    color: "bg-rose-50 text-rose-700 border-rose-200",
  },
  {
    key: "答辩状",
    label: "答辩状",
    description: "针对对方起诉状进行逐条答辩与反驳。",
    icon: Gavel,
    placeholder: "请描述被诉案件信息：原告主张、争议焦点、我方答辩理由、相关证据等。",
    color: "bg-orange-50 text-orange-700 border-orange-200",
  },
  {
    key: "自由起草",
    label: "自由起草",
    description: "不限类型，自定义提示词生成任意合同或法律文书。",
    icon: PenLine,
    placeholder: "请输入任意合同或法律文书的起草需求，AI 将根据描述生成完整文书。",
    color: "bg-slate-50 text-slate-700 border-slate-200",
  },
];

/* ============ 各类型结构化框架（schema 驱动） ============ */
type FormField = {
  key: string;
  label: string;
  placeholder?: string;
  span?: boolean;
  kind?: "text" | "textarea";
  default?: string;
};
type FormSection = { title: string; hint?: string; fields: FormField[] };

const FORM_SCHEMAS: Record<string, FormSection[]> = {
  销售合同: [
    {
      title: "合同主体",
      hint: "甲方为卖方，乙方为买方",
      fields: [
        { key: "sellerName", label: "甲方（卖方）· 公司名称", placeholder: "例：云起科技有限公司" },
        { key: "buyerName", label: "乙方（买方）· 公司名称", placeholder: "例：宏达贸易有限公司" },
        { key: "sellerAddress", label: "甲方地址", placeholder: "例：广东省深圳市南山区…" },
        { key: "buyerAddress", label: "乙方地址", placeholder: "例：广东省广州市天河区…" },
        { key: "sellerContact", label: "甲方联系人 / 电话", placeholder: "例：张三 13800000000" },
        { key: "buyerContact", label: "乙方联系人 / 电话", placeholder: "例：李四 13900000000" },
      ],
    },
    {
      title: "标的物与价款",
      hint: "填写货物与价格",
      fields: [
        { key: "productName", label: "标的物品名", placeholder: "例：工业服务器 200 台" },
        { key: "productSpec", label: "规格型号", placeholder: "例：R740 32G/2T" },
        { key: "quantity", label: "数量", placeholder: "例：200" },
        { key: "unitPrice", label: "单价（元）", placeholder: "例：15000" },
        { key: "totalAmount", label: "合同总价（元）", placeholder: "例：3000000" },
        { key: "currency", label: "币种", placeholder: "人民币", default: "人民币" },
      ],
    },
    {
      title: "交付与验收",
      hint: "货物交付安排",
      fields: [
        { key: "deliveryMethod", label: "交付方式", placeholder: "例：物流运输，运费由卖方承担" },
        { key: "deliveryPlace", label: "交付地点", placeholder: "例：乙方指定仓库" },
        { key: "deliveryDate", label: "交付期限", placeholder: "例：合同签订后 30 日内" },
      ],
    },
    {
      title: "付款方式",
      hint: "货款结算安排",
      fields: [
        { key: "paymentMethod", label: "付款方式", placeholder: "例：签订后支付 30% 定金，货到验收合格后支付 70% 尾款" },
        { key: "paymentDate", label: "付款期限", placeholder: "例：验收合格后 7 日内" },
      ],
    },
    {
      title: "违约与补充",
      hint: "可选，留空使用标准条款",
      fields: [
        { key: "breach", label: "违约责任", kind: "textarea", default: "逾期交货或逾期付款的，每逾期一日按合同总价 0.05% 向守约方支付违约金" },
        { key: "notes", label: "补充说明", kind: "textarea", placeholder: "其他需要写入合同的内容（如质保期、开票要求、特别约定等）…" },
      ],
    },
  ],
  采购合同: [
    {
      title: "合同主体",
      hint: "甲方为采购方，乙方为供应商",
      fields: [
        { key: "buyerName", label: "甲方（采购方）· 公司名称", placeholder: "例：宏达贸易有限公司" },
        { key: "supplierName", label: "乙方（供应商）· 公司名称", placeholder: "例：云起科技有限公司" },
        { key: "buyerAddress", label: "甲方地址", placeholder: "例：广东省广州市天河区…" },
        { key: "supplierAddress", label: "乙方地址", placeholder: "例：广东省深圳市南山区…" },
        { key: "buyerContact", label: "甲方联系人 / 电话", placeholder: "例：李四 13900000000" },
        { key: "supplierContact", label: "乙方联系人 / 电话", placeholder: "例：张三 13800000000" },
      ],
    },
    {
      title: "标的物与价款",
      hint: "填写采购物品与价格",
      fields: [
        { key: "productName", label: "采购物品名", placeholder: "例：办公电脑 100 台" },
        { key: "productSpec", label: "规格型号", placeholder: "例：i7/16G/512G" },
        { key: "quantity", label: "数量", placeholder: "例：100" },
        { key: "unitPrice", label: "单价（元）", placeholder: "例：8000" },
        { key: "totalAmount", label: "合同总价（元）", placeholder: "例：800000" },
        { key: "currency", label: "币种", placeholder: "人民币", default: "人民币" },
      ],
    },
    {
      title: "交付与验收",
      hint: "交货与验收安排",
      fields: [
        { key: "deliveryMethod", label: "交货方式", placeholder: "例：供应商负责运输至采购方仓库" },
        { key: "deliveryPlace", label: "交货地点", placeholder: "例：采购方指定仓库" },
        { key: "deliveryDate", label: "交货期限", placeholder: "例：合同签订后 20 日内" },
        { key: "acceptance", label: "验收标准", placeholder: "例：按国家标准验收，7 日内提出异议" },
      ],
    },
    {
      title: "付款方式",
      hint: "货款结算安排",
      fields: [
        { key: "paymentMethod", label: "付款方式", placeholder: "例：货到验收合格后 30 日内一次性支付" },
        { key: "paymentDate", label: "付款期限", placeholder: "例：验收合格后 30 日内" },
      ],
    },
    {
      title: "违约与补充",
      hint: "可选，留空使用标准条款",
      fields: [
        { key: "breach", label: "违约责任", kind: "textarea", default: "逾期交货或逾期付款的，每逾期一日按合同总价 0.05% 向守约方支付违约金" },
        { key: "notes", label: "补充说明", kind: "textarea", placeholder: "其他需要写入合同的内容…" },
      ],
    },
  ],
  服务合同: [
    {
      title: "合同主体",
      hint: "甲方为委托方，乙方为服务方",
      fields: [
        { key: "clientName", label: "甲方（委托方）· 名称", placeholder: "例：恒信科技股份有限公司" },
        { key: "serviceName", label: "乙方（服务方）· 名称", placeholder: "例：智达咨询有限公司" },
        { key: "clientAddress", label: "甲方地址", placeholder: "例：北京市朝阳区…" },
        { key: "serviceAddress", label: "乙方地址", placeholder: "例：上海市浦东新区…" },
        { key: "clientContact", label: "甲方联系人 / 电话", placeholder: "例：王五 13700000000" },
        { key: "serviceContact", label: "乙方联系人 / 电话", placeholder: "例：赵六 13600000000" },
      ],
    },
    {
      title: "服务内容",
      hint: "明确服务范围与交付标准",
      fields: [
        { key: "serviceScope", label: "服务内容", placeholder: "例：信息系统运维、年度咨询服务…" },
        { key: "servicePeriod", label: "服务期限", placeholder: "例：自 2026-09-01 至 2027-08-31" },
        { key: "serviceStandard", label: "交付标准", placeholder: "例：每月提交服务报告，重大故障 2 小时内响应" },
      ],
    },
    {
      title: "服务费用",
      hint: "费用与支付安排",
      fields: [
        { key: "serviceFee", label: "服务费用（元）", placeholder: "例：120000" },
        { key: "paymentMethod", label: "支付方式", placeholder: "例：合同签订后支付 50%，验收合格后支付 50%" },
      ],
    },
    {
      title: "保密与违约",
      hint: "可选，留空使用标准条款",
      fields: [
        { key: "confidentiality", label: "保密义务", kind: "textarea", placeholder: "例：双方对知悉的商业秘密承担保密义务，期限为合同终止后 3 年" },
        { key: "breach", label: "违约责任", kind: "textarea", default: "任何一方违约给对方造成损失的，应承担赔偿责任" },
      ],
    },
    {
      title: "补充说明",
      hint: "其他约定",
      fields: [{ key: "notes", label: "补充说明", kind: "textarea", placeholder: "其他需要写入合同的内容…" }],
    },
  ],
  劳动合同: [
    {
      title: "用工主体",
      hint: "用人单位与员工信息",
      fields: [
        { key: "employer", label: "用人单位·名称", placeholder: "例：云起科技有限公司" },
        { key: "employee", label: "员工·姓名", placeholder: "例：张三" },
        { key: "employerAddress", label: "用人单位地址", placeholder: "例：广东省深圳市…" },
        { key: "employeeId", label: "员工身份证号", placeholder: "例：440300200001011234" },
        { key: "employerContact", label: "用人单位联系人", placeholder: "例：HR 李经理 0755-88888888" },
        { key: "employeeContact", label: "员工联系电话", placeholder: "例：13800000000" },
      ],
    },
    {
      title: "岗位与期限",
      hint: "工作岗位与合同期限",
      fields: [
        { key: "position", label: "工作岗位", placeholder: "例：软件工程师" },
        { key: "contractPeriod", label: "合同期限", placeholder: "例：固定期限三年，自 2026-09-01 至 2029-08-31" },
        { key: "workPlace", label: "工作地点", placeholder: "例：深圳市南山区" },
        { key: "workHours", label: "工作时间", placeholder: "例：标准工时制，周一至周五 9:00-18:00" },
      ],
    },
    {
      title: "薪酬待遇",
      hint: "薪资与社会保险",
      fields: [
        { key: "salary", label: "月薪（元）", placeholder: "例：15000" },
        { key: "probation", label: "试用期（月）", placeholder: "例：3" },
        { key: "probationSalary", label: "试用期工资（元）", placeholder: "例：12000" },
        { key: "insurance", label: "社会保险", placeholder: "例：依法缴纳五险一金" },
      ],
    },
    {
      title: "其他约定",
      hint: "可选",
      fields: [
        { key: "otherClauses", label: "其他约定", kind: "textarea", placeholder: "例：竞业限制、保密协议、培训服务期等…" },
      ],
    },
  ],
  起诉状: [
    {
      title: "当事人",
      hint: "原告与被告信息",
      fields: [
        { key: "plaintiff", label: "原告·姓名/名称", placeholder: "例：张三（或某公司）" },
        { key: "defendant", label: "被告·姓名/名称", placeholder: "例：李四（或某公司）" },
        { key: "plaintiffAddress", label: "原告住址/地址", placeholder: "例：广东省深圳市…" },
        { key: "defendantAddress", label: "被告住址/地址", placeholder: "例：广东省广州市…" },
        { key: "plaintiffContact", label: "原告联系方式", placeholder: "例：13800000000" },
        { key: "defendantContact", label: "被告联系方式", placeholder: "例：13900000000" },
      ],
    },
    {
      title: "诉讼请求",
      hint: "请求法院支持的事项",
      fields: [
        { key: "claims", label: "诉讼请求", kind: "textarea", placeholder: "例：1. 判令被告偿还借款 100000 元及利息；2. 本案诉讼费由被告承担…" },
      ],
    },
    {
      title: "事实与理由",
      hint: "陈述案件事实",
      fields: [
        { key: "facts", label: "事实与理由", kind: "textarea", placeholder: "按时间顺序描述借款/交易/纠纷经过…" },
        { key: "legalBasis", label: "法律依据（可选）", placeholder: "例：《民法典》第六百六十七条…" },
      ],
    },
    {
      title: "证据线索",
      hint: "可附证据材料",
      fields: [
        { key: "evidence", label: "证据清单", kind: "textarea", placeholder: "例：1. 借款合同；2. 转账记录；3. 微信聊天记录…" },
      ],
    },
  ],
  答辩状: [
    {
      title: "案件信息",
      hint: "被诉案件基本信息",
      fields: [
        { key: "caseNumber", label: "案号", placeholder: "例：（2026）粤 03 民初 123 号" },
        { key: "court", label: "受理法院", placeholder: "例：深圳市中级人民法院" },
        { key: "plaintiffClaim", label: "原告主张", kind: "textarea", placeholder: "概括原告起诉的主要请求与理由…" },
      ],
    },
    {
      title: "答辩意见",
      hint: "逐条反驳与抗辩",
      fields: [
        { key: "defense", label: "答辩意见", kind: "textarea", placeholder: "针对原告主张逐条答辩：1. 对…不予认可，因为…" },
        { key: "disputeFocus", label: "争议焦点", placeholder: "例：借款是否实际交付、利息计算标准等" },
      ],
    },
    {
      title: "事实与理由",
      hint: "陈述我方事实",
      fields: [
        { key: "facts", label: "事实与理由", kind: "textarea", placeholder: "按时间顺序描述事实经过，反驳原告主张…" },
      ],
    },
    {
      title: "证据线索",
      hint: "可附证据材料",
      fields: [
        { key: "evidence", label: "证据清单", kind: "textarea", placeholder: "例：1. 还款凭证；2. 银行流水；3. 通话录音…" },
      ],
    },
  ],
};

const IMAGE_TYPES = "image/jpeg,image/png,image/webp,image/jpg";
const AUDIO_TYPES = "audio/mpeg,audio/wav,audio/x-m4a,audio/mp3,audio/m4a";

type UploadedFile = {
  name: string;
  size: number;
  type: string;
  base64: string;
};

export function DraftingCenter() {
  const navigate = useNavigate();
  const [selectedType, setSelectedType] = useState<DraftType | null>(null);
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [genStartedAt, setGenStartedAt] = useState(0);
  const [error, setError] = useState("");
  const imageRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLInputElement>(null);

  // 框架表单：所有类型共用动态字段值
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const setValue = (key: string, v: string) => setFormValues((prev) => ({ ...prev, [key]: v }));

  const schema = selectedType ? FORM_SCHEMAS[selectedType.key] : undefined;

  // 按 schema 组装提示词
  const buildRequirements = () => {
    const lines: string[] = [`请根据以下信息生成一份完整、专业的《${selectedType?.key || ""}》：`, ""];
    (schema || []).forEach((section) => {
      lines.push(`【${section.title}】`);
      section.fields.forEach((f) => {
        const v = (formValues[f.key] ?? "").trim();
        if (v) lines.push(`- ${f.label}：${v}`);
      });
      lines.push("");
    });
    lines.push("请按标准文书结构生成完整内容（合同含：合同主体信息、标的、价款、交付/履行、付款、违约责任、争议解决、生效条款等）。");
    return lines.filter(Boolean).join("\n");
  };

  // 框架表单提交（各类型统一）
  const handleFrameworkSubmit = async () => {
    if (!selectedType) return;
    const filled = (schema || []).some((s) => s.fields.some((f) => (formValues[f.key] ?? "").trim()));
    if (!filled) {
      setError("请至少填写一项信息，才能生成文书");
      return;
    }
    setLoading(true);
    setGenStartedAt(Date.now());
    setError("");
    try {
      const requirements = buildRequirements();
      const request: ContractGenerateRequest = {
        contract_type: selectedType.key,
        requirements,
        description: requirements,
      };
      const response = await generateContract(request);
      navigate(`/drafting/editor/${response.contract_id}?type=${encodeURIComponent(selectedType.key)}`);
    } catch (err: any) {
      setError(err?.message || "生成失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList) return;
    const newFiles: UploadedFile[] = [];
    for (const file of Array.from(fileList)) {
      const base64 = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsDataURL(file);
      });
      newFiles.push({ name: file.name, size: file.size, type: file.type, base64 });
    }
    setFiles((prev) => [...prev, ...newFiles]);
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // 自由起草（无框架）：提示词输入
  const handlePromptSubmit = async () => {
    if (!selectedType) return;
    if (!prompt.trim() && files.length === 0) {
      setError("请输入提示词或上传至少一个材料");
      return;
    }
    setLoading(true);
    setGenStartedAt(Date.now());
    setError("");
    try {
      const request: ContractGenerateRequest = {
        contract_type: selectedType.key,
        requirements: prompt.trim(),
        description: prompt.trim(),
        materials_text: files.length
          ? `用户上传了以下材料：${files.map((f) => f.name).join("、")}\n\n${files.map((f) => `[${f.type}] ${f.name}`).join("\n")}`
          : undefined,
        materials: files.map((f) => ({
          name: f.name,
          size: f.size,
          type: f.type,
          text_extracted: false,
          base64: f.base64,
        })),
      };
      const response = await generateContract(request);
      navigate(`/drafting/editor/${response.contract_id}?type=${encodeURIComponent(selectedType.key)}`);
    } catch (err: any) {
      setError(err?.message || "生成失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setSelectedType(null);
    setPrompt("");
    setFiles([]);
    setError("");
    setFormValues({});
  };

  // 框架表单视图（有 schema 的类型）
  if (selectedType && schema) {
    const TypeIcon = selectedType.icon;
    const Field = ({ f }: { f: FormField }) => (
      <div className={cn("space-y-1.5", f.span && "sm:col-span-2")}>
        <label className="block text-[10px] font-black tracking-widest text-muted-foreground">{f.label}</label>
        {f.kind === "textarea" ? (
          <textarea
            value={formValues[f.key] ?? f.default ?? ""}
            onChange={(e) => setValue(f.key, e.target.value)}
            placeholder={f.placeholder}
            rows={f.key === "facts" || f.key === "claims" || f.key === "defense" ? 5 : 3}
            className="w-full resize-none rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium text-foreground outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-primary/50 focus:ring-2 focus:ring-primary/10"
          />
        ) : (
          <input
            value={formValues[f.key] ?? f.default ?? ""}
            onChange={(e) => setValue(f.key, e.target.value)}
            placeholder={f.placeholder}
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium text-foreground outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-primary/50 focus:ring-2 focus:ring-primary/10"
          />
        )}
      </div>
    );
    return (
      <div className="max-w-5xl space-y-6 pb-20 pt-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            onClick={reset}
            className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2 text-xs font-black text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> 返回选择类型
          </button>
          <div className="flex items-center gap-3">
            <div className={cn("flex h-11 w-11 items-center justify-center rounded-2xl border", selectedType.color)}>
              <TypeIcon className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-2xl font-black tracking-wide text-foreground">{selectedType.label}</h1>
              <p className="text-xs font-bold text-muted-foreground">填写文书框架信息，AI 直接生成完整文书</p>
            </div>
          </div>
        </div>

        {schema.map((section, si) => (
          <section key={si} className="rounded-[1.5rem] border border-border bg-card/90 p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <div className="text-sm font-black text-foreground">{section.title}</div>
              {section.hint && <span className="text-[10px] font-bold text-muted-foreground">{section.hint}</span>}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {section.fields.map((f) => (
                <Field key={f.key} f={f} />
              ))}
            </div>
          </section>
        ))}

        {error && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs font-bold text-rose-700">{error}</div>
        )}

        <button
          onClick={() => void handleFrameworkSubmit()}
          disabled={loading}
          className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-primary px-6 py-3.5 text-sm font-black text-primary-foreground shadow-sm transition-all hover:shadow-md disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          {loading ? "正在生成…" : "生成合同"}
        </button>
        {loading && (
          <TaskProgress
            title={`AI 起草${selectedType.label}`}
            phases={["解析文书框架信息", "匹配法规与条款", "起草正文", "风险检查"]}
            startedAt={genStartedAt}
            className="mt-3"
          />
        )}
      </div>
    );
  }

  // 自由起草视图（无框架）：提示词 + 上传
  if (selectedType) {
    const TypeIcon = selectedType.icon;
    return (
      <div className="max-w-4xl pb-20 pt-8">
        <button
          onClick={reset}
          className="mb-6 inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2 text-xs font-black text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> 返回选择类型
        </button>

        <div className="rounded-[2rem] border border-border bg-card/85 px-8 py-8 shadow-sm">
          <div className="mb-6 flex items-center gap-3">
            <div className={cn("flex h-12 w-12 items-center justify-center rounded-2xl border", selectedType.color)}>
              <TypeIcon className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-2xl font-black tracking-wide text-foreground">{selectedType.label}</h1>
              <p className="text-xs font-bold text-muted-foreground">{selectedType.description}</p>
            </div>
          </div>

          <div className="space-y-4">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={selectedType.placeholder}
              rows={8}
              className="w-full resize-none rounded-2xl border border-border bg-secondary/30 px-5 py-4 text-sm font-medium leading-relaxed text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
            />

            {files.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {files.map((file, idx) => (
                  <div
                    key={`${file.name}-${idx}`}
                    className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs font-bold text-foreground shadow-sm"
                  >
                    {file.type.startsWith("image/") ? <Image className="h-3.5 w-3.5 text-primary" /> : <Mic className="h-3.5 w-3.5 text-primary" />}
                    <span className="max-w-[200px] truncate">{file.name}</span>
                    <button
                      onClick={() => removeFile(idx)}
                      className="ml-1 rounded-full p-0.5 text-muted-foreground hover:bg-rose-50 hover:text-rose-600"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => imageRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-xs font-black text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <Image className="h-4 w-4" /> 上传图片
              </button>
              <button
                onClick={() => audioRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-xs font-black text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <Mic className="h-4 w-4" /> 上传语音
              </button>
              <input
                ref={imageRef}
                type="file"
                accept={IMAGE_TYPES}
                multiple
                className="hidden"
                onChange={(e) => void handleFiles(e.target.files)}
              />
              <input
                ref={audioRef}
                type="file"
                accept={AUDIO_TYPES}
                multiple
                className="hidden"
                onChange={(e) => void handleFiles(e.target.files)}
              />
            </div>

            {error && (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs font-bold text-rose-700">{error}</div>
            )}

            <button
              onClick={() => void handlePromptSubmit()}
              disabled={loading || (!prompt.trim() && files.length === 0)}
              className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-primary px-6 py-3.5 text-sm font-black text-primary-foreground shadow-sm transition-all hover:shadow-md disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {loading ? "正在生成…" : "开始生成"}
            </button>
            {loading && (
              <TaskProgress
                title={`AI 起草${selectedType.label}`}
                phases={["解析需求", "匹配法规与条款", "起草正文", "风险检查"]}
                startedAt={genStartedAt}
                className="mt-3"
              />
            )}
          </div>
        </div>
      </div>
    );
  }

  // 类型选择视图
  return (
    <div className="max-w-7xl space-y-8 pb-20 pt-8">
      <PageHeader
        title="合同文书起草"
        description="选择文书类型，填写框架信息或直接描述需求，AI 自动生成专业文书。"
      />

      <section className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {DRAFT_TYPES.map((type) => {
          const Icon = type.icon;
          return (
            <button
              key={type.key}
              onClick={() => setSelectedType(type)}
              className={cn(
                "group relative flex flex-col rounded-[1.5rem] border bg-card p-6 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md",
                type.color.replace("bg-", "hover:border-").split(" ")[2]
              )}
            >
              <div className={cn("mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border", type.color)}>
                <Icon className="h-6 w-6" />
              </div>
              <div className="text-sm font-black text-foreground">{type.label}</div>
              <div className="mt-2 text-xs font-bold leading-5 text-muted-foreground">{type.description}</div>
              <div className="mt-4 flex items-center gap-1 text-xs font-black text-primary opacity-0 transition-opacity group-hover:opacity-100">
                <FileText className="h-3.5 w-3.5" /> 点击开始起草
              </div>
            </button>
          );
        })}
      </section>
    </div>
  );
}
