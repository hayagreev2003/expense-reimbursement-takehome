import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Home from '../page';

describe('Home', () => {
  it('names all three roles the workflow has to serve', () => {
    render(<Home />);

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Travel expense settlement',
    );
    for (const role of ['Employee', 'Approver', 'Finance']) {
      expect(screen.getByRole('heading', { level: 2, name: role })).toBeInTheDocument();
    }
  });
});
