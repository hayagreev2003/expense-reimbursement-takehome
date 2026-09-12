'use client';

import { queryClient } from '@/app/providers';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useEmployees } from '@/features/claim-review/hooks/useClaim';
import { useRole } from '@/store/role';

/** Stands in for authentication, which is out of scope — see docs/NOTE.md. */
export function RoleSwitcher() {
  const { data: employees } = useEmployees();
  const { empCode, setEmpCode } = useRole();

  return (
    <Select
      value={empCode ?? undefined}
      onValueChange={code => {
        setEmpCode(code);
        // Evict everything the previous role loaded. An approver must never see a queue
        // that was built for someone else.
        queryClient.clear();
      }}
    >
      <SelectTrigger className="w-[280px]">
        <SelectValue placeholder="Acting as…" />
      </SelectTrigger>
      <SelectContent>
        {(employees ?? []).map(person => (
          <SelectItem key={person.emp_code} value={person.emp_code}>
            {person.name} — {person.role}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
