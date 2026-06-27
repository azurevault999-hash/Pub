import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  ArrowRight, ArrowLeft, Search, ChevronDown, CheckCircle2,
  AlertTriangle, XCircle, RefreshCw, Shield,
} from "lucide-react";
import {
  useRunValidation,
  useGetValidation,
  getGetValidationQueryKey,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import type { ValidationIssue } from "@workspace/api-client-react";

interface ValidationStepProps {
  sessionId: string;
  onNext: () => void;
  onBack: () => void;
}

function LevelBadge({ level }: { level: ValidationIssue["level"] }) {
  if (level === "pass") return <Badge className="bg-green-500/15 text-green-500 border-green-500/30 text-xs">PASS</Badge>;
  if (level === "warning") return <Badge className="bg-yellow-500/15 text-yellow-500 border-yellow-500/30 text-xs">WARN</Badge>;
  return <Badge className="bg-red-500/15 text-red-500 border-red-500/30 text-xs">ERROR</Badge>;
}

function IssueRow({ issue }: { issue: ValidationIssue }) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <div
          className="flex items-start gap-3 py-3 px-4 hover:bg-muted/40 cursor-pointer transition-colors border-b border-border last:border-0"
          data-testid={`row-validation-${issue.check.replace(/\s+/g, "-").toLowerCase()}`}
        >
          <div className="mt-0.5 w-16 shrink-0">
            <LevelBadge level={issue.level} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">{issue.check}</p>
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{issue.message}</p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {issue.count > 0 && (
              <span className="text-xs font-mono text-muted-foreground bg-muted px-2 py-0.5 rounded">
                {issue.count}
              </span>
            )}
            {issue.details.length > 0 && (
              <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
            )}
          </div>
        </div>
      </CollapsibleTrigger>
      {issue.details.length > 0 && (
        <CollapsibleContent>
          <div className="px-4 pb-3 pt-1 bg-muted/20">
            <div className="font-mono text-xs text-muted-foreground space-y-1 pl-[76px]">
              {issue.details.slice(0, 20).map((d: string, i: number) => (
                <div key={i} className="flex gap-2">
                  <span className="text-muted-foreground/50 w-5 shrink-0">{i + 1}.</span>
                  <span className="break-all">{d}</span>
                </div>
              ))}
              {issue.details.length > 20 && (
                <div className="text-muted-foreground/60 italic">…and {issue.details.length - 20} more</div>
              )}
            </div>
          </div>
        </CollapsibleContent>
      )}
    </Collapsible>
  );
}

function GroupPanel({ title, issues, icon: Icon, className }: {
  title: string;
  issues: ValidationIssue[];
  icon: React.ElementType;
  className: string;
}) {
  const [open, setOpen] = useState(true);
  if (issues.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className={`border ${className}`}>
        <CollapsibleTrigger asChild>
          <CardHeader className="pb-0 cursor-pointer hover:opacity-80 transition-opacity">
            <CardTitle className="text-sm font-semibold flex items-center justify-between">
              <span className="flex items-center gap-2">
                <Icon className="w-4 h-4" />
                {title} <span className="font-mono text-muted-foreground ml-1">({issues.length})</span>
              </span>
              <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
            </CardTitle>
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="pt-3 pb-0">
            <div className="divide-y divide-border -mx-6">
              {issues.map((issue, i) => <IssueRow key={i} issue={issue} />)}
            </div>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}

export function ValidationStep({ sessionId, onNext, onBack }: ValidationStepProps) {
  const [search, setSearch] = useState("");
  const queryClient = useQueryClient();

  const runValidation = useRunValidation();
  const { data: validationData, isLoading: validationLoading } = useGetValidation(
    sessionId,
    { query: { enabled: !!sessionId, queryKey: getGetValidationQueryKey(sessionId) } }
  );

  const handleRunValidation = () => {
    runValidation.mutate(
      { sessionId },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getGetValidationQueryKey(sessionId) });
        },
      }
    );
  };

  const isRunning = runValidation.isPending;
  const hasData = !!validationData;

  const filtered = hasData
    ? validationData.issues.filter(
        (i) =>
          i.check.toLowerCase().includes(search.toLowerCase()) ||
          i.message.toLowerCase().includes(search.toLowerCase())
      )
    : [];

  const errors = filtered.filter((i) => i.level === "error");
  const warnings = filtered.filter((i) => i.level === "warning");
  const passes = filtered.filter((i) => i.level === "pass");

  return (
    <div className="w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight mb-1">Validation Engine</h2>
          <p className="text-muted-foreground text-sm">
            Run comprehensive checks before converting. Errors must be resolved; warnings are advisory.
          </p>
        </div>
        <Button
          onClick={handleRunValidation}
          disabled={isRunning}
          variant={hasData ? "outline" : "default"}
          size="sm"
          className="shrink-0"
          data-testid="button-run-validation"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${isRunning ? "animate-spin" : ""}`} />
          {isRunning ? "Running…" : hasData ? "Re-run" : "Run Validation"}
        </Button>
      </div>

      {/* Not run yet */}
      {!hasData && !isRunning && !validationLoading && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Shield className="w-12 h-12 text-muted-foreground/40 mb-4" />
            <p className="text-muted-foreground text-sm">No validation results yet.</p>
            <p className="text-muted-foreground/60 text-xs mt-1">Click "Run Validation" to start.</p>
          </CardContent>
        </Card>
      )}

      {/* Loading skeleton */}
      {(isRunning || validationLoading) && (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full rounded-lg" />
          ))}
        </div>
      )}

      {/* Results */}
      {hasData && !isRunning && (
        <>
          {/* Summary bar */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-3 text-center">
              <p className="text-2xl font-bold text-green-500 tabular-nums">{validationData.pass_count}</p>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mt-0.5">Passed</p>
            </div>
            <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3 text-center">
              <p className="text-2xl font-bold text-yellow-500 tabular-nums">{validationData.warning_count}</p>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mt-0.5">Warnings</p>
            </div>
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-center">
              <p className="text-2xl font-bold text-red-500 tabular-nums">{validationData.error_count}</p>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mt-0.5">Errors</p>
            </div>
          </div>

          {!validationData.can_convert && (
            <Alert variant="destructive">
              <XCircle className="h-4 w-4" />
              <AlertDescription>
                {validationData.error_count} error(s) detected. Resolve them in your source data before converting.
              </AlertDescription>
            </Alert>
          )}

          {validationData.can_convert && (
            <Alert className="border-green-500/30 bg-green-500/5 text-green-600 dark:text-green-400">
              <CheckCircle2 className="h-4 w-4" />
              <AlertDescription>Validation passed — ready to convert.</AlertDescription>
            </Alert>
          )}

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search checks…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
              data-testid="input-search-validation"
            />
          </div>

          {/* Grouped panels */}
          <div className="space-y-4">
            <GroupPanel
              title="Errors"
              issues={errors}
              icon={XCircle}
              className="border-red-500/20"
            />
            <GroupPanel
              title="Warnings"
              issues={warnings}
              icon={AlertTriangle}
              className="border-yellow-500/20"
            />
            <GroupPanel
              title="Passed Checks"
              issues={passes}
              icon={CheckCircle2}
              className="border-green-500/20"
            />
          </div>
        </>
      )}

      <div className="flex items-center justify-between pt-2">
        <Button variant="ghost" onClick={onBack} size="sm" data-testid="button-back-analysis">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back
        </Button>
        <Button
          onClick={onNext}
          disabled={!hasData || !validationData?.can_convert}
          size="lg"
          data-testid="button-next-conversion"
        >
          Generate WooCommerce CSV
          <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );
}
