'use client';

import { ApiError } from '@/api/error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useFieldArray, useForm } from 'react-hook-form';
import { z } from 'zod';
import { useCorrectDocument } from '../hooks/useEvidence';

const MONEY = /^\d{1,9}(\.\d{1,2})?$/;

const money = (message: string) => z.string().trim().regex(MONEY, message);

const schema = z.object({
  merchant: z.string().trim().max(200).optional(),
  bill_no: z.string().trim().max(60).optional(),
  stated_total: z
    .string()
    .trim()
    .refine(value => value === '' || MONEY.test(value), 'An amount, e.g. 19200.00')
    .optional(),
  lines: z
    .array(
      z.object({
        description: z.string().trim().min(2, 'What is this charge?').max(300),
        gross_amount: money('An amount, e.g. 5750.00'),
        txn_date: z.string().min(1, 'What date?'),
        nights: z
          .string()
          .trim()
          .refine(value => value === '' || /^\d{1,3}$/.test(value), 'A whole number of nights')
          .optional(),
        paid_by: z.enum(['Employee', 'Company']),
      }),
    )
    .min(1),
});

type Values = z.infer<typeof schema>;

const BLANK = {
  description: '',
  gross_amount: '',
  txn_date: '',
  nights: '',
  paid_by: 'Employee',
} as const;

/**
 * Entering a bill's figures when nothing could read them.
 *
 * Every line is entered separately rather than as one total, because that is what policy needs:
 * a folio is a room charge, a meal and a laundry charge with three different outcomes, and one
 * lump sum cannot be judged. The merchant and the bill number are asked once - they belong to
 * the bill, not to each line on it.
 *
 * The total printed on the bill is optional and is a guard: give it and the server refuses the
 * correction unless the lines add up to it, which is the same check it applies to a bill it read
 * itself.
 */
export function CorrectionPanel({
  trqId,
  externalId,
  filename,
  onDone,
}: {
  trqId: string;
  externalId: string;
  filename: string;
  onDone: () => void;
}) {
  const correct = useCorrectDocument(trqId);
  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { lines: [{ ...BLANK }] },
  });
  const lines = useFieldArray({ control, name: 'lines' });

  const submit = handleSubmit(values => {
    correct.mutate(
      {
        externalId,
        correction: {
          stated_total: values.stated_total || null,
          lines: values.lines.map(line => ({
            description: line.description,
            gross_amount: line.gross_amount,
            txn_date: line.txn_date,
            nights: line.nights ? Number(line.nights) : null,
            paid_by: line.paid_by,
            merchant: values.merchant || null,
            bill_no: values.bill_no || null,
          })),
        },
      },
      { onSuccess: onDone },
    );
  });

  return (
    <form onSubmit={submit} className="bg-muted/40 mt-2 space-y-3 rounded-lg border p-3" noValidate>
      <p className="text-sm">
        Enter what <span className="font-mono text-xs">{filename}</span> says. Each charge on the
        bill is its own line — policy treats a room charge, a meal and a laundry charge differently,
        so a single total cannot be assessed.
      </p>

      <div className="grid gap-3 sm:grid-cols-3">
        <Labelled label="Merchant">
          <Input placeholder="Lemon Tree Premier" {...register('merchant')} />
        </Labelled>
        <Labelled label="Bill number">
          <Input placeholder="LT/1188" {...register('bill_no')} />
        </Labelled>
        <Labelled
          label="Total on the bill (optional)"
          error={errors.stated_total?.message}
          hint="Given, the lines must add up to it."
        >
          <Input inputMode="decimal" placeholder="19200.00" {...register('stated_total')} />
        </Labelled>
      </div>

      {lines.fields.map((field, index) => (
        <div key={field.id} className="grid gap-2 border-t pt-3 sm:grid-cols-12">
          <div className="sm:col-span-4">
            <Labelled label="Charge" error={errors.lines?.[index]?.description?.message}>
              <Input
                placeholder="Room tariff, 3 nights"
                {...register(`lines.${index}.description`)}
              />
            </Labelled>
          </div>
          <div className="sm:col-span-2">
            <Labelled label="Amount" error={errors.lines?.[index]?.gross_amount?.message}>
              <Input
                inputMode="decimal"
                placeholder="17250.00"
                {...register(`lines.${index}.gross_amount`)}
              />
            </Labelled>
          </div>
          <div className="sm:col-span-2">
            <Labelled label="Date" error={errors.lines?.[index]?.txn_date?.message}>
              <Input type="date" {...register(`lines.${index}.txn_date`)} />
            </Labelled>
          </div>
          <div className="sm:col-span-2">
            <Labelled
              label="Nights"
              error={errors.lines?.[index]?.nights?.message}
              hint="Lodging only"
            >
              <Input inputMode="numeric" placeholder="3" {...register(`lines.${index}.nights`)} />
            </Labelled>
          </div>
          <div className="sm:col-span-2">
            <Labelled label="Paid by">
              <Controller
                control={control}
                name={`lines.${index}.paid_by`}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Employee">I paid</SelectItem>
                      <SelectItem value="Company">Company card</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </Labelled>
          </div>
          {lines.fields.length > 1 && (
            <div className="sm:col-span-12">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => lines.remove(index)}
                aria-label={`Remove line ${index + 1}`}
              >
                Remove this line
              </Button>
            </div>
          )}
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-3 border-t pt-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => lines.append({ ...BLANK })}
        >
          Add another charge
        </Button>
        <Button type="submit" size="sm" disabled={correct.isPending}>
          {correct.isPending ? 'Saving…' : 'Save these figures'}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onDone}
          disabled={correct.isPending}
        >
          Cancel
        </Button>
        {correct.error && (
          <span className="text-sm text-rose-700">
            {(correct.error as ApiError).userMessage ?? 'Those figures were not accepted.'}
          </span>
        )}
      </div>
    </form>
  );
}

function Labelled({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium">{label}</span>
      {children}
      {hint && !error && <span className="text-muted-foreground block text-xs">{hint}</span>}
      {error && <span className="block text-xs text-rose-700">{error}</span>}
    </label>
  );
}
