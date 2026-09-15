'use client';

import { ApiError } from '@/api/error';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';
import { CITY_CLASSES, TRAVEL_MODES } from '../api/trips';
import { useCreateTrip } from '../hooks/useCreateTrip';

const MONEY = /^\d{1,9}(\.\d{1,2})?$/;

const schema = z
  .object({
    destination_city: z.string().trim().min(2, 'Where are you going?').max(80),
    from_date: z.string().min(1, 'When does the trip start?'),
    to_date: z.string().min(1, 'When do you get back?'),
    purpose: z.string().trim().min(4, 'A line on why the trip is needed.').max(300),
    city_class: z.enum(['Tier 1', 'Tier 2', 'Tier 3']),
    mode_of_travel: z.enum(TRAVEL_MODES),
    visiting_company: z.string().trim().max(160).optional(),
    advance_requested: z
      .string()
      .trim()
      .refine(value => value === '' || MONEY.test(value), 'An amount in rupees, e.g. 20000.00')
      .optional(),
  })
  // Checked here as well as on the server, because the browser is where it can be said next to
  // the field that is wrong.
  .refine(values => values.to_date >= values.from_date, {
    message: 'The trip cannot end before it begins.',
    path: ['to_date'],
  });

type Values = z.infer<typeof schema>;

/**
 * Applying for a trip.
 *
 * The trip is what a claim is filed against, so this is the entry point to everything else: it
 * comes into being empty, and the bills arrive afterwards. Only the fields policy actually reads
 * are asked for - city class decides the §3.1 lodging limit, the dates decide the §5.1 deadline
 * and which policy revision applies, and an advance is a request rather than money disbursed.
 */
export function NewTripForm({
  onCreated,
  onCancel,
}: {
  onCreated: (trqId: string) => void;
  onCancel: () => void;
}) {
  const create = useCreateTrip();
  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { city_class: 'Tier 1', mode_of_travel: 'Flight' },
  });

  const submit = handleSubmit(values => {
    create.mutate(
      {
        destination_city: values.destination_city,
        from_date: values.from_date,
        to_date: values.to_date,
        purpose: values.purpose,
        city_class: values.city_class,
        mode_of_travel: values.mode_of_travel,
        visiting_company: values.visiting_company || null,
        advance_requested: values.advance_requested || null,
      },
      { onSuccess: trip => onCreated(trip.trq_id) },
    );
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Apply for a trip</CardTitle>
        <p className="text-muted-foreground text-sm">
          This creates the Travel Request your claim is filed against. Add the bills as they come in
          — you have seven days from the date you get back to submit (§5.1).
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Destination" error={errors.destination_city?.message}>
              <Input placeholder="Bengaluru" {...register('destination_city')} />
            </Field>

            <Field label="City class" error={errors.city_class?.message}>
              <Controller
                control={control}
                name="city_class"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CITY_CLASSES.map(option => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            <Field label="Leaving on" error={errors.from_date?.message}>
              <Input type="date" {...register('from_date')} />
            </Field>

            <Field label="Back on" error={errors.to_date?.message}>
              <Input type="date" {...register('to_date')} />
            </Field>

            <Field label="Travelling by" error={errors.mode_of_travel?.message}>
              <Controller
                control={control}
                name="mode_of_travel"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TRAVEL_MODES.map(mode => (
                        <SelectItem key={mode} value={mode}>
                          {mode}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            <Field label="Visiting (optional)" error={errors.visiting_company?.message}>
              <Input placeholder="Vertex Technologies" {...register('visiting_company')} />
            </Field>
          </div>

          <Field label="Purpose" error={errors.purpose?.message}>
            <Textarea
              placeholder="Quarterly review with the customer's procurement team."
              maxLength={300}
              {...register('purpose')}
            />
          </Field>

          <Field
            label="Advance requested (optional)"
            error={errors.advance_requested?.message}
            hint="A request, not money in hand. Finance disburses it separately, and only a disbursed advance is settled against the claim."
          >
            <Input inputMode="decimal" placeholder="20000.00" {...register('advance_requested')} />
          </Field>

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Applying…' : 'Apply'}
            </Button>
            <Button type="button" variant="ghost" onClick={onCancel} disabled={create.isPending}>
              Cancel
            </Button>
            {create.error && (
              <span className="text-sm text-rose-700">
                {(create.error as ApiError).userMessage ?? 'The application could not be made.'}
              </span>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function Field({
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
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && !error && <span className="text-muted-foreground block text-xs">{hint}</span>}
      {error && <span className="block text-xs text-rose-700">{error}</span>}
    </label>
  );
}
